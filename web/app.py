from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import requests
import os
from datetime import datetime
import logging
from composite_services.utilities.activity_logger import log_activity
import secrets
import pika
import json 

app = Flask(__name__, static_folder="web/static", static_url_path="/static")
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(16))

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Microservice URLs
PLAYER_SERVICE_URL = os.getenv("PLAYER_SERVICE_URL", "http://player_service:5000")
ENTERING_ROOM_SERVICE_URL = os.getenv("ENTERING_ROOM_SERVICE_URL", "http://entering_room_service:5011")
PICK_UP_ITEM_SERVICE_URL = os.getenv("PICK_UP_ITEM_SERVICE_URL", "http://pick_up_item_service:5019")
OPEN_INVENTORY_SERVICE_URL = os.getenv("OPEN_INVENTORY_SERVICE_URL", "http://open_inventory_service:5010")
ITEM_SERVICE_URL = os.getenv("ITEM_SERVICE_URL", "http://item_service:5020")
ROOM_SERVICE_URL = os.getenv("ROOM_SERVICE_URL", "http://room_service:5030")
COMBAT_SERVICE_URL = os.getenv("COMBAT_SERVICE_URL", "http://fight_enemy_service:5009")
ACTIVITY_LOG_SERVICE_URL = os.getenv("ACTIVITY_LOG_SERVICE_URL", "http://activity_log_service:5013")
PLAYER_ROOM_INTERACTION_SERVICE_URL = os.getenv("PLAYER_ROOM_INTERACTION_SERVICE_URL", "http://player_room_interaction_service:5040")
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://inventory_service:5001")
MANAGE_GAME_SERVICE_URL = os.getenv("MANAGE_GAME_SERVICE_URL", "http://manage_game_service:5014")
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")

# Add login routes
@app.route("/login", methods=["GET"])
def login_page():
    """Renders the login page."""
    if 'player_id' in session:
        return redirect(url_for('home'))
    return render_template("login.html")

@app.route("/login", methods=["POST"])
def login():
    """Logs in an existing player or creates a new one."""
    data = request.form
    player_name = data.get('player_name')
    character_class = data.get('character_class', 'Warrior')
    
    if not player_name:
        return jsonify({"error": "Player name is required"}), 400
    
    # Check if player exists
    try:
        # Try to find player by name
        player_search_response = requests.get(
            f"{PLAYER_SERVICE_URL}/player/name/{player_name}",
            timeout=5  # Add timeout to prevent long waits
        )
        
        if player_search_response.status_code == 200:
            # Player exists, use existing ID
            player_data = player_search_response.json()
            # Extract player ID from response - check all possible key names
            player_id = player_data.get('PlayerID') or player_data.get('player_id')
            logger.info(f"Player '{player_name}' found, ID: {player_id}")
            
            # Reset game state for existing player
            try:
                requests.post(
                    f"{MANAGE_GAME_SERVICE_URL}/game/full-reset/{player_id}",
                    timeout=5
                )
                logger.info(f"Game reset for existing player {player_id} during login")
            except Exception as e:
                logger.error(f"Failed to reset game during login: {str(e)}")
                
            session['player_id'] = player_id
            session['player_name'] = player_name
            return redirect(url_for('home'))
        
        elif player_search_response.status_code == 404:
            # Player not found, create new player
            return create_new_player(player_name, character_class)
        else:
            logger.error(f"Unexpected response from player service: {player_search_response.status_code} - {player_search_response.text}")
            # Fall back to attempting to create a new player
            return create_new_player(player_name, character_class)
    
    except requests.RequestException as e:
        logger.error(f"Request error when calling player service: {str(e)}")
        # Fall back to attempting to create a new player
        return create_new_player(player_name, character_class)

def create_new_player(player_name, character_class):
    """Helper function to create a new player."""
    try:
        logger.info(f"Attempting to create new player: {player_name}, class: {character_class}")
        new_player_response = requests.post(
            f"{PLAYER_SERVICE_URL}/player",
            json={"name": player_name, "character_class": character_class},
            timeout=5
        )
        
        if new_player_response.status_code == 201:
            player_data = new_player_response.json()
            logger.debug(f"Player creation response: {player_data}")
            
            # The player ID is nested inside the "player" object
            player_obj = player_data.get('player', {})
            # Try both possible key names
            player_id = player_obj.get('player_id') or player_obj.get('PlayerID')
            
            if not player_id:
                logger.error(f"Failed to extract player ID from response: {player_data}")
                return jsonify({"error": "Failed to extract player ID from response"}), 500
            
            logger.info(f"New player '{player_name}' created successfully, ID: {player_id}")
            
            session['player_id'] = player_id
            session['player_name'] = player_name
            return redirect(url_for('home'))
        elif new_player_response.status_code == 409:
            # Player name already exists - this can happen if the player was created between our check and creation
            logger.warn(f"Player name '{player_name}' already exists, trying to retrieve existing player")
            # Try to retrieve the existing player
            try:
                retry_response = requests.get(
                    f"{PLAYER_SERVICE_URL}/player/name/{player_name}",
                    timeout=5
                )
                if retry_response.status_code == 200:
                    player_data = retry_response.json()
                    player_id = player_data.get('PlayerID') or player_data.get('player_id')
                    
                    session['player_id'] = player_id
                    session['player_name'] = player_name
                    return redirect(url_for('home'))
                else:
                    logger.error(f"Failed to retrieve player after 409 conflict: {retry_response.text}")
                    return jsonify({"error": "Player name already exists but could not retrieve player"}), 500
            except Exception as e:
                logger.error(f"Error retrieving player after 409 conflict: {str(e)}")
                return jsonify({"error": f"Player name already exists but could not retrieve player: {str(e)}"}), 500
        else:
            logger.error(f"Failed to create new player: {new_player_response.status_code} - {new_player_response.text}")
            return jsonify({"error": f"Failed to create new player: {new_player_response.text}"}), 500
    except requests.RequestException as e:
        logger.error(f"Request error when creating new player: {str(e)}")
        return jsonify({"error": f"Failed to connect to player service: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"Unexpected error creating new player: {str(e)}")
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

@app.route("/logout", methods=["GET"])
def logout():
    """Logs out the current player and resets their game state."""
    player_id = session.get('player_id')
    
    # Reset game state if player_id exists
    if player_id:
        try:
            # Call the manage_game_service to reset the game
            requests.post(
                f"{MANAGE_GAME_SERVICE_URL}/game/full-reset/{player_id}",
                timeout=5
            )
            logger.info(f"Game reset for player {player_id} during logout")
        except Exception as e:
            logger.error(f"Failed to reset game during logout: {str(e)}")
    
    # Clear session data
    session.pop('player_id', None)
    session.pop('player_name', None)
    
    return redirect(url_for('login_page'))

# Helper function to get current player ID
def get_current_player_id():
    """Gets the current player ID from the session or returns None if not logged in."""
    return session.get('player_id')

# Middleware to check if player is logged in
@app.before_request
def check_logged_in():
    """Ensures the player is logged in for protected routes."""
    # List of routes that don't require login
    public_routes = ['login', 'login_page', 'logout', 'static']
    
    # Check if the route requires login
    if request.endpoint not in public_routes and 'player_id' not in session:
        # If it's an API route or AJAX request, return JSON error
        if request.path.startswith('/api/') or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"error": "Not logged in"}), 401
        # Otherwise redirect to login page
        return redirect(url_for('login_page'))

@app.route("/")
def home():
    """Renders the game UI."""
    player_id = session.get('player_id')
    player_name = session.get('player_name')
    
    if player_id is None:
        logger.error(f"Player ID is None for player name: {player_name}")
        # Redirect to login if player_id is missing
        return redirect(url_for('login_page'))
        
    return render_template("index.html", player_id=player_id, player_name=player_name)

@app.route("/get_player_room", methods=["GET"])
def get_player_room():
    """Gets the player's current room ID."""
    player_id = get_current_player_id()

    # Get player data from player service
    response = requests.get(f"{PLAYER_SERVICE_URL}/player/{player_id}")
    if response.status_code != 200:
        logger.error(f"Failed to get player data: {response.text}")
        return jsonify({"error": "Could not retrieve player data"}), response.status_code

    player_data = response.json()
    logger.debug(f"Raw player data from service: {player_data}")
    
    # Check for both uppercase and lowercase key variants
    room_id = player_data.get("RoomID")
    logger.debug(f"RoomID from response: {room_id}")
    
    if room_id is None:
        room_id = player_data.get("room_id", 0)
        logger.debug(f"room_id from response (or default 0): {room_id}")
    
    # Ensure we have an integer value
    if room_id is not None:
        try:
            room_id = int(room_id)
        except (ValueError, TypeError):
            logger.error(f"Invalid room_id value: {room_id}, defaulting to 0")
            room_id = 0
    
    # Set room_id to 0 if it's somehow still None
    if room_id is None:
        logger.warning("room_id is still None after checks, forcing to 0")
        room_id = 0
        
    logger.debug(f"GET /get_player_room - Final room ID: {room_id}")
    return jsonify({"room_id": room_id})

@app.route("/enter_room", methods=["POST"])
def enter_room():
    """Proxy to the composite service."""
    data = request.get_json() or {}
    
    # Set default player ID
    if "player_id" not in data:
        data["player_id"] = get_current_player_id()
    
    player_id = data["player_id"]
    
    # Handle target_room_id if provided (for room refresh after combat)
    target_room_id = data.get("target_room_id")
    
    if target_room_id is not None:
        logger.debug(f"Target room ID provided: {target_room_id}. Refreshing current room for player {player_id}.")
        # Direct call to specific room endpoint
        room_url = f"{ENTERING_ROOM_SERVICE_URL}/room/{target_room_id}"
    else:
        # Use the next room endpoint which increments the room
        logger.debug(f"No target room ID - using next_room endpoint for player {player_id}.")
        room_url = f"{ENTERING_ROOM_SERVICE_URL}/next_room"
    
    try:
        logger.debug(f"Forwarding request to {room_url}")
        response = requests.post(room_url, json=data)
        
        # Check for room-specific errors first
        if response.status_code == 403:
            # Locked door or enemies present - just pass through
            return jsonify(response.json()), response.status_code
            
        # Check if the response status code indicates room not found (404)
        # which might mean we've reached the end of the game
        if response.status_code == 404 and not target_room_id:
            try:
                # Parse the response to check if this is truly the end of the game
                error_data = response.json()
                
                # Check if this is a room that doesn't exist response (end of game)
                if "room not found" in error_data.get("error", "").lower():
                    # Get the current player room to check if it's beyond what we have
                    player_response = requests.get(f"{PLAYER_SERVICE_URL}/player/{player_id}")
                    if player_response.status_code == 200:
                        player_data = player_response.json()
                        current_room = player_data.get("RoomID", player_data.get("room_id", 0))
                        
                        # If player is already beyond room 3, it's definitely end of game
                        if current_room >= 3:
                            logger.info(f"End of game detected - player in room {current_room} trying to go beyond")
                            return create_end_of_game_response(player_id)
                    
                    # If we can't determine the room, just pass through the 404
                    return jsonify(error_data), 404
                
                # For other 404s, pass through
                return jsonify(error_data), 404
            except Exception as e:
                logger.error(f"Error parsing 404 response: {str(e)}")
                # If we can't parse it, assume it's not end of game
                return jsonify({"error": "Room not found"}), 404
        
        # For successful responses, just pass through
        return jsonify(response.json()), response.status_code
        
    except requests.RequestException as e:
        logger.error(f"Error connecting to entering_room service: {str(e)}")
        return jsonify({"error": "Failed to connect to room service"}), 500

def create_end_of_game_response(player_id, message="Congratulations! You've completed the game!"):
    """
    Creates a response for when the game is finished
    """
    try:
        # Call the manage_game service to handle end-of-game logic
        response = requests.post(
            f"{MANAGE_GAME_SERVICE_URL}/game/end/{player_id}",
            json={"message": message},
            timeout=5
        )
        
        if response.status_code == 200:
            response_data = response.json()
            return jsonify(response_data), 200
        else:
            logger.error(f"Failed to process end of game: {response.status_code}")
            return jsonify({
                "message": message,
                "player_score": 0,
                "score_message": "Unable to retrieve score",
                "error": "Failed to process end of game"
            }), 200
    except Exception as e:
        logger.error(f"Error in end of game: {str(e)}")
        return jsonify({
            "message": message,
            "player_score": 0,
            "score_message": "Unable to retrieve score",
            "error": str(e)
        }), 200

@app.route("/pick_up_item", methods=["POST"])
def pick_up_item():
    """Proxy to the pick_up_item composite service."""
    data = request.get_json()
    room_id = data.get('room_id')
    item_id = data.get('item_id')
    
    # Get player_id from the request first, fallback to session if not provided
    player_id = data.get('player_id')
    if not player_id:
        player_id = get_current_player_id()
        
    logger.debug(f"POST /pick_up_item - Delegating to pick_up_item service for player {player_id}")
    
    if not room_id or not item_id:
        return jsonify({"error": "Room ID and Item ID are required"}), 400
    
    if not player_id:
        return jsonify({"error": "Player ID is required"}), 400
    
    # Add player_id to the request
    pickup_data = {"player_id": player_id}
    
    # Simply pass the request to the composite service
    try:
        pickup_url = f"{PICK_UP_ITEM_SERVICE_URL}/room/{room_id}/item/{item_id}/pickup"
        response = requests.post(pickup_url, json=pickup_data)
        
        # Pass through the response
        return jsonify(response.json()), response.status_code
    except requests.RequestException as e:
        logger.error(f"Error connecting to pick_up_item service: {str(e)}")
        return jsonify({"error": f"Failed to connect to pick up item service: {str(e)}"}), 500

@app.route("/view_inventory", methods=["GET"])
def view_inventory():
    """Retrieves the player's inventory with item details."""
    # Check for player_id in query parameters first, fallback to session
    player_id = request.args.get('player_id')
    if not player_id:
        player_id = get_current_player_id()

    logger.debug(f"GET /view_inventory - Retrieving inventory for player ID: {player_id}")

    if not player_id:
        return jsonify({"error": "Player ID is required"}), 400

    # Log the inventory view activity
    log_activity(player_id, "Viewed inventory")

    # Call the open_inventory service
    inventory_url = f"{OPEN_INVENTORY_SERVICE_URL}/inventory/{player_id}"
    logger.debug(f"Calling inventory service: {inventory_url}")

    response = requests.get(inventory_url)
    logger.debug(f"Inventory service response: {response.status_code} - {response.text}")

    if response.status_code != 200:
        logger.error(f"Failed to retrieve inventory: {response.text}")
        return jsonify({"error": "Failed to retrieve inventory"}), response.status_code

    # The inventory data already contains the enhanced items with descriptions
    inventory_data = response.json()

    return jsonify({
        "player_id": player_id,
        "items": inventory_data.get("inventory", [])
    })

@app.route("/fetch_item_details", methods=["GET"])
def fetch_item_details():
    """Fetches details for a specific item."""
    item_id = request.args.get('item_id')

    if not item_id:
        return jsonify({"error": "Item ID is required"}), 400

    # Call the item service to get item details
    item_url = f"{ITEM_SERVICE_URL}/item/{item_id}"
    logger.debug(f"Fetching item details from: {item_url}")

    response = requests.get(item_url)
    logger.debug(f"Item service response: {response.status_code} - {response.text}")

    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch item details"}), response.status_code

    return jsonify(response.json())

@app.route("/fetch_item_details_batch", methods=["POST"])
def fetch_item_details_batch_endpoint():
    """Endpoint for fetching details for multiple items at once."""
    data = request.get_json()
    item_ids = data.get('item_ids', [])
    
    if not item_ids:
        return jsonify({"error": "Item IDs are required"}), 400
    
    items = fetch_item_details_batch(item_ids)
    return jsonify({"items": items})

def fetch_item_details_batch(item_ids):
    """
    Helper function to fetch details for a batch of items.
    Can be called directly by other functions.
    """
    try:
        # Call the open_inventory service batch endpoint
        response = requests.post(
            f"{OPEN_INVENTORY_SERVICE_URL}/items/batch",
            json={"item_ids": item_ids},
            timeout=5
        )
        
        if response.status_code == 200:
            return response.json().get("items", [])
        else:
            logger.error(f"Failed to fetch item details: {response.status_code}")
            return []
    except Exception as e:
        logger.error(f"Error fetching item details: {str(e)}")
        return []

@app.route("/room_info/<int:room_id>", methods=["GET"])
def get_room_info(room_id):
    """Gets room information without entering the room."""
    player_id = get_current_player_id()
    logger.debug(f"GET /room_info/{room_id} - Checking room info for player {player_id}")

    # This endpoint just forwarded to the room service
    room_url = f"{ROOM_SERVICE_URL}/room/{room_id}?player_id={player_id}"
    logger.debug(f"Calling room service: {room_url}")

    response = requests.get(room_url)
    if response.status_code != 200:
        logger.error(f"Failed to get room info: {response.text}")
        return jsonify({"error": "Room not found"}), 404

    return jsonify(response.json())

@app.route("/player_stats", methods=["GET"])
def player_stats():
    """Retrieves the player's stats from the player service."""
    # Check for player_id in query parameters first, fallback to session
    player_id = request.args.get('player_id')
    if not player_id:
        player_id = get_current_player_id()

    logger.debug(f"GET /player_stats - Retrieving stats for player ID: {player_id}")

    if not player_id:
        return jsonify({"error": "Player ID is required"}), 400

    # Call the player service to get player data
    player_url = f"{PLAYER_SERVICE_URL}/player/{player_id}"
    logger.debug(f"Calling player service: {player_url}")

    try:
        response = requests.get(player_url)
        logger.debug(f"Player service response: {response.status_code} - {response.text}")

        if response.status_code != 200:
            logger.error(f"Failed to retrieve player stats: {response.text}")
            return jsonify({"error": "Failed to retrieve player stats"}), response.status_code

        # Return the player data
        player_data = response.json()
        return jsonify(player_data)

    except requests.RequestException as e:
        logger.error(f"Request error when calling player service: {str(e)}")
        return jsonify({"error": "Failed to connect to player service"}), 500

@app.route("/combat/start/<int:enemy_id>", methods=["POST"])
def start_combat(enemy_id):
    """Starts combat with an enemy"""
    player_id = get_current_player_id()
    
    # Call the fight_enemy service
    combat_url = f"{COMBAT_SERVICE_URL}/combat/start/{enemy_id}"
    combat_data = {"player_id": player_id}
    
    try:
        response = requests.post(combat_url, json=combat_data)
        
        if response.status_code != 200:
            return jsonify({"error": "Failed to start combat"}), response.status_code
        
        # Just pass through the response from the combat service
        return jsonify(response.json())
    except requests.RequestException as e:
        logger.error(f"Request error when calling combat service: {str(e)}")
        return jsonify({"error": "Failed to connect to combat service"}), 500

@app.route("/combat/attack", methods=["POST"])
def combat_attack():
    """Proxy to the fight_enemy composite service."""
    player_id = get_current_player_id()
    data = request.get_json()
    
    logger.debug(f"POST /combat/attack - Delegating to fight_enemy service for player {player_id}")
    
    # Add player_id if not present
    if "player_id" not in data:
        data["player_id"] = player_id
    
    # Simply pass the request to the composite service
    try:
        attack_url = f"{COMBAT_SERVICE_URL}/combat/attack"
        response = requests.post(attack_url, json=data)
        
        # Pass through the response
        return jsonify(response.json()), response.status_code
    except requests.RequestException as e:
        logger.error(f"Error connecting to combat service: {str(e)}")
        return jsonify({"error": f"Failed to connect to combat service: {str(e)}"}), 500


        
@app.route("/hard_reset", methods=["POST"])
def hard_reset():
    """
    Performs a complete hard reset of the player's game state by calling the manage_game service.
    This is more thorough than the regular reset and is intended for debugging.
    """
    data = request.get_json()
    player_id = data.get("player_id")
    
    if not player_id:
        return jsonify({"error": "Player ID is required"}), 400
        
    logger.info(f"Requesting HARD RESET for player {player_id} via manage_game service")
    
    try:
        # Call the manage_game service to perform the hard reset
        response = requests.post(
            f"{MANAGE_GAME_SERVICE_URL}/game/hard-reset/{player_id}",
            timeout=10
        )
        
        # Return the response from the manage_game service
        if response.status_code == 200:
            result = response.json()
            logger.info(f"Hard reset completed for player {player_id}")
            return jsonify(result)
        else:
            logger.error(f"Failed to perform hard reset: {response.status_code} - {response.text}")
            try:
                error_data = response.json()
                return jsonify(error_data), response.status_code
            except:
                return jsonify({"error": f"Failed to perform hard reset: {response.status_code}"}), response.status_code
    except requests.RequestException as e:
        logger.error(f"Error connecting to manage_game service: {str(e)}")
        return jsonify({
            "success": False,
            "message": f"Failed to connect to game management service: {str(e)}"
        }), 500

@app.route('/player_activity_logs', methods=['GET'])
@app.route('/player_activity_logs/<int:player_id>', methods=['GET'])
def player_activity_logs(player_id=None):
    """
    Display player activity logs
    """
    # If player_id is not provided in URL, get it from session
    if not player_id:
        player_id = get_current_player_id()
        
    if not player_id:
        return jsonify({"error": "Player ID is required"}), 400
    
    try:
        # Call activity log service directly
        response = requests.get(
            f"{ACTIVITY_LOG_SERVICE_URL}/log/{player_id}",
            timeout=5
        )
        
        if response.status_code == 200:
            logs = response.json()
            return jsonify({"logs": logs}), 200
        else:
            logger.error(f"Failed to retrieve activity logs: {response.status_code}")
            return jsonify({"error": "Failed to retrieve activity logs"}), response.status_code
    except Exception as e:
        logger.error(f"Error retrieving activity logs: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)
