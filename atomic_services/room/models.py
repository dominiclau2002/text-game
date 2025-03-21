import os
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# Define the Room Database Model
class RoomModel(db.Model):
    __tablename__ = "Room"

    RoomID = db.Column(db.Integer, primary_key=True, autoincrement=True)
    Description = db.Column(db.String(500), nullable=False)
    ItemIDs = db.Column(db.JSON, nullable=True, default=[])
    EnemyIDs = db.Column(db.JSON, nullable=True, default=[])
    DoorLocked = db.Column(db.Boolean, nullable=False, default=False)

    def to_dict(self):
        return {
            "RoomID": self.RoomID,
            "Description": self.Description,
            "ItemIDs": self.ItemIDs,
            "EnemyIDs": self.EnemyIDs,
            "DoorLocked": self.DoorLocked
        }

def init_db(app):
    # Database Configuration
    DATABASE_URL = os.getenv("DATABASE_URL", "mysql+mysqlconnector://user:password@mysql:3307/room_db")
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    
    with app.app_context():
        db.create_all() 