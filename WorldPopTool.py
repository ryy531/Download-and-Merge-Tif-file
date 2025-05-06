import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import os
import sys
import subprocess
import importlib.util
import logging

# Setup logging
logging.basicConfig(
    filename='worldpoptool.log',
    level=logging.DEBUG, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class WorldPopTool:
    def __init__(self, root):
        self.root = root
        self.root.title("WorldPop Data Processing Tool")
        self.root.geometry("700x550")
        self.root.minsize(700, 550)
        
        logging.debug("Initializing WorldPopTool application")
        
        # Set up the main frame
        main_frame = ttk.Frame(root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(main_frame, text="WorldPop Data Processing Tool", font=("Arial", 16, "bold"))
        title_label.pack(pady=(0, 20))
        
        # Introduction text
        intro_text = "This tool provides a unified interface for processing WorldPop data through four sequential steps."
        intro_label = ttk.Label(main_frame, text=intro_text, wraplength=650)
        intro_label.pack(pady=(0, 20))
        
        # Create notebook for tabbed interface
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True)
        
        # Create tabs
        workflow_tab = ttk.Frame(notebook)
        about_tab = ttk.Frame(notebook)
        notebook.add(workflow_tab, text="Workflow")
        notebook.add(about_tab, text="About")
        
        # Set up workflow tab
        self.setup_workflow_tab(workflow_tab)
        
        # Set up about tab
        self.setup_about_tab(about_tab)
        
        # Status bar
        self.status_var = tk.StringVar()
        self.status_var.set("Ready")
        status_bar = ttk.Label(root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        logging.debug("WorldPopTool initialization complete")
    
    def setup_workflow_tab(self, parent):
        # Create frame for steps
        steps_frame = ttk.Frame(parent)
        steps_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Create and configure each step button with description
        self.create_step_button(
            steps_frame, 
            "Step 1: Download TIFF Files", 
            "Downloads TIFF files from WorldPop website. Requires a WorldPop summary URL.", 
            0,
            self.run_step1
        )
        
        self.create_step_button(
            steps_frame, 
            "Step 2: Convert TIFF to CSV", 
            "Converts a TIFF file to CSV format, extracting coordinates and population data.", 
            1,
            self.run_step2
        )
        
        self.create_step_button(
            steps_frame, 
            "Step 3: Process Multiple TIFFs", 
            "Processes multiple TIFF files and combines them into a single comprehensive CSV file.", 
            2,
            self.run_step3
        )
        
        self.create_step_button(
            steps_frame, 
            "Step 4: Combine Age Groups", 
            "Adds summary columns for specified age ranges in the processed CSV file.", 
            3,
            self.run_step4
        )
    
    def setup_about_tab(self, parent):
        about_frame = ttk.Frame(parent, padding=20)
        about_frame.pack(fill=tk.BOTH, expand=True)
        
        about_text = """WorldPop Data Processing Tool

This application provides a unified interface for processing WorldPop demographic data through four sequential steps:

1. Download TIFF Files - Downloads population data TIFF files from the WorldPop website
2. Convert TIFF to CSV - Converts raster TIFF data to point-based CSV format
3. Process Multiple TIFFs - Combines multiple demographic TIFF files into a single dataset
4. Combine Age Groups - Creates summary columns for specified age ranges

Requirements:
- Python 3.6+
- GDAL library
- BeautifulSoup4
- Requests
- Pandas
- NumPy

For issues or questions, please check the log file (worldpoptool.log) for troubleshooting information.
        """
        
        about_textbox = scrolledtext.ScrolledText(about_frame, wrap=tk.WORD, width=80, height=20)
        about_textbox.insert(tk.END, about_text)
        about_textbox.configure(state='disabled')
        about_textbox.pack(fill=tk.BOTH, expand=True)
    
    def create_step_button(self, parent, title, description, row, command):
        step_frame = ttk.LabelFrame(parent, text=title)
        step_frame.grid(row=row, column=0, padx=5, pady=5, sticky="ew")
        parent.grid_columnconfigure(0, weight=1)
        
        desc_label = ttk.Label(step_frame, text=description, wraplength=600)
        desc_label.pack(side=tk.LEFT, padx=10, pady=10, fill=tk.BOTH, expand=True)
        
        run_button = ttk.Button(step_frame, text="Run", command=command, width=10)
        run_button.pack(side=tk.RIGHT, padx=10, pady=10)
    
    def run_step1(self):
        self.status_var.set("Running Step 1: TIFF Downloader...")
        self.root.update()
        self.run_script("Step1Downloader.py")
    
    def run_step2(self):
        self.status_var.set("Running Step 2: TIFF to CSV Converter...")
        self.root.update()
        self.run_script("Step2CentroidLToCSVExporter.py")
    
    def run_step3(self):
        self.status_var.set("Running Step 3: Multiple TIFF Processor...")
        self.root.update()
        self.run_script("Step3ProcessMultipleTifs.py")
    
    def run_step4(self):
        self.status_var.set("Running Step 4: Age Group Combiner...")
        self.root.update()
        self.run_script("Step4CombineAgeGroup.py")
    
    def run_script(self, script_name):
        try:
            logging.debug(f"Attempting to run script: {script_name}")
            
            # Get the path of the current script
            if getattr(sys, 'frozen', False):
                # We are running in a bundle (PyInstaller executable)
                base_path = sys._MEIPASS
                logging.debug(f"Running in frozen environment, base path: {base_path}")
            else:
                # We are running in a normal Python environment
                base_path = os.path.dirname(os.path.abspath(__file__))
                logging.debug(f"Running in normal environment, base path: {base_path}")
            
            script_path = os.path.join(base_path, script_name)
            logging.debug(f"Script path: {script_path}")
            
            # Check if script exists
            if not os.path.exists(script_path):
                error_msg = f"Script file not found: {script_path}"
                logging.error(error_msg)
                raise FileNotFoundError(error_msg)
            
            # Check if we're running as executable or as script
            if getattr(sys, 'frozen', False):
                # When running as executable, import the module and call main function
                logging.debug(f"Importing script as module: {script_name}")
                spec = importlib.util.spec_from_file_location(script_name, script_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                if hasattr(module, 'main'):
                    logging.debug(f"Calling main() function in {script_name}")
                    module.main()
                else:
                    # If no main function, assume the script runs on import
                    logging.debug(f"No main() function found in {script_name}, assuming it ran on import")
            else:
                # When running as script, use subprocess to run the Python file
                logging.debug(f"Running script via subprocess: {script_path}")
                subprocess.run([sys.executable, script_path], check=True)
            
            logging.debug(f"Successfully completed running: {script_name}")
            self.status_var.set("Ready")
        except Exception as e:
            error_message = f"An error occurred while running {script_name}: {str(e)}"
            logging.error(error_message, exc_info=True)
            self.status_var.set(f"Error: {str(e)}")
            messagebox.showerror("Error", error_message)

# Make sure the GDAL_DATA environment variable is set correctly when frozen
def setup_gdal_environment():
    if getattr(sys, 'frozen', False):
        try:
            from osgeo import gdal
            gdal_data_path = os.path.join(sys._MEIPASS, 'gdal', 'data')
            if os.path.exists(gdal_data_path):
                os.environ['GDAL_DATA'] = gdal_data_path
                logging.debug(f"Set GDAL_DATA environment variable to {gdal_data_path}")
            else:
                logging.warning(f"GDAL data directory not found at {gdal_data_path}")
        except ImportError:
            logging.warning("Could not import GDAL to set up environment")

if __name__ == "__main__":
    try:
        logging.debug("Starting WorldPopTool application")
        setup_gdal_environment()
        root = tk.Tk()
        app = WorldPopTool(root)
        root.mainloop()
    except Exception as e:
        logging.critical("Fatal error in main program", exc_info=True)
        messagebox.showerror("Fatal Error", f"A critical error occurred: {str(e)}\nCheck worldpoptool.log for details.")