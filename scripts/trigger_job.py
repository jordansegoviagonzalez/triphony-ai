import sys
import os
import uuid
import time
from dotenv import load_dotenv

# 1. Load environment variables from services/api/.env
# This is crucial because we are running from the project root, 
# but the app expects the .env in its own folder or loaded into env vars.
env_path = os.path.abspath("services/api/.env")
if os.path.exists(env_path):
    print(f"Loading environment from: {env_path}")
    load_dotenv(env_path)
else:
    print(f"Warning: .env not found at {env_path}")

# 2. Setup Python Path to find project modules
# We need to add the source directories for api, worker, and shared code.
sys.path.append(os.path.abspath("services/api/src"))
sys.path.append(os.path.abspath("services/worker/src"))
sys.path.append(os.path.abspath("src"))

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from api.settings import settings
    from api.models import Scene, Asset, AssetType, SceneStatus
    from worker.tasks import generate_asset
except ImportError as e:
    print(f"Error importing project modules: {e}")
    print("Ensure you are running this script from the project root with the virtual environment activated.")
    sys.exit(1)

def create_job():
    print("\n--- 🎬 Triphony AI Art Studio Trigger Script ---")
    
    # Verify DB Connection
    print(f"Target Database: {settings.database_url}")
    
    try:
        engine = create_engine(settings.database_url)
        Session = sessionmaker(bind=engine)
        session = Session()
    except Exception as e:
        print(f"❌ Error connecting to database: {e}")
        print("Did you run 'docker-compose up -d'?")
        return

    # Create a Scene
    scene_id = str(uuid.uuid4())
    prompt = "Cinematic shot of a cybernetic samurai in a neon-lit rainy street, 8k, highly detailed, 35mm lens"
    
    print(f"Creating Scene ID: {scene_id}")
    print(f"Prompt: {prompt}")
    
    scene = Scene(id=scene_id, prompt=prompt, status=SceneStatus.queued)
    session.add(scene)
    
    # Create Visual Asset (The Video)
    print("Creating 'visual' asset entry...")
    asset = Asset(scene_id=scene_id, asset_type=AssetType.visual)
    session.add(asset)
    
    session.commit()
    print("✅ Database records created.")
    
    # Trigger Celery Task
    print(f"🚀 Triggering Celery task for Scene {scene_id}...")
    
    try:
        # We pass the scene_id and asset_type to the worker
        generate_asset.delay(scene_id=scene_id, asset_type="visual")
        print("✅ Task sent to queue!")
        print("\nTo see the result:")
        print("1. Ensure your Celery worker is running.")
        print(f"2. Check the 'artifacts/{scene_id}/visual' directory in a few minutes.")
    except Exception as e:
        print(f"❌ Failed to send task to Redis: {e}")
        print("Ensure Redis is running (docker-compose up -d).")
    
    session.close()

if __name__ == "__main__":
    create_job()
