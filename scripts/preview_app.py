import sys, os
sys.path.insert(0, 'app'); os.makedirs('data', exist_ok=True)
import main
from database import create_db_and_tables, seed_initial_data
create_db_and_tables(); seed_initial_data()
from nicegui import ui
ui.run(port=8092, show=False, reload=False, storage_secret='preview')
