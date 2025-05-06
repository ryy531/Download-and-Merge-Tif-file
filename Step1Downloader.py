import tkinter as tk
from tkinter import filedialog, messagebox
import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import threading

# Function to fetch the content of a webpage
def getWebPageContent(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"Error fetching URL {url}: {e}")
        return None

# Function to extract all TIFF file URLs from the HTML content
def extractTiffUrls(htmlContent):
    soup = BeautifulSoup(htmlContent, 'html.parser')
    tiffUrls = []
    for link in soup.find_all('a', href=True):
        href = link['href']
        if href.endswith('.tif'):
            if not href.startswith('http'):
                href = "https://data.worldpop.org" + href
            tiffUrls.append(href)
    return tiffUrls

# Function to create a new download folder
def createDownloadFolder(baseDirectory, folderName):
    downloadPath = os.path.join(baseDirectory, folderName)
    os.makedirs(downloadPath, exist_ok=True)
    return downloadPath

# Function to download a single file
def downloadFile(url, savePath):
    try:
        filename = os.path.basename(url)
        filePath = os.path.join(savePath, filename)
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(filePath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        print(f"Downloaded: {filename}")
    except requests.RequestException as e:
        print(f"Error downloading {url}: {e}")

# Function to choose save directory using GUI
def chooseSaveDirectory(root):
    directory = filedialog.askdirectory(parent=root, title="Select Directory to Save Files")
    return directory

# Function to set status label
def setStatus(message):
    status_label.config(text=message)

# Function to show info message
def showInfo(message):
    messagebox.showinfo("Info", message)

# Function to show error message
def showError(message):
    messagebox.showerror("Error", message)

# Function to perform download in a separate thread
def performDownload(url, save_dir, user_folder_name, root):
    root.after(0, setStatus, "Fetching webpage...")
    html_content = getWebPageContent(url)
    if not html_content:
        root.after(0, showError, "Failed to fetch webpage")
        root.after(0, setStatus, "Ready")
        root.after(0, lambda: start_button.config(state=tk.NORMAL))
        return
    
    root.after(0, setStatus, "Extracting TIFF URLs...")
    tiff_urls = extractTiffUrls(html_content)
    if not tiff_urls:
        root.after(0, showError, "No TIFF files found on the page")
        root.after(0, setStatus, "Ready")
        root.after(0, lambda: start_button.config(state=tk.NORMAL))
        return
    
    download_path = createDownloadFolder(save_dir, user_folder_name)
    root.after(0, setStatus, f"Files will be saved in: {download_path}")
    
    for i, tiff_url in enumerate(tiff_urls):
        status_msg = f"Downloading file {i+1}/{len(tiff_urls)}: {os.path.basename(tiff_url)}"
        root.after(0, setStatus, status_msg)
        downloadFile(tiff_url, download_path)
    
    root.after(0, setStatus, "Download Complete")
    root.after(0, showInfo, "All files have been downloaded")
    root.after(0, lambda: start_button.config(state=tk.NORMAL))

# Main GUI setup
if __name__ == "__main__":
    # Generate default folder name with timestamp
    default_folder_name = f"TIFF_Downloads_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    root = tk.Tk()
    root.title("WorldPop TIFF Downloader")
    
    url_label = tk.Label(root, text="Enter the WorldPop summary URL:")
    url_label.pack()
    
    url_entry = tk.Entry(root, width=50)
    url_entry.pack()
    
    folder_label = tk.Label(root, text="Folder name (modify or keep default):")
    folder_label.pack()
    
    folder_entry = tk.Entry(root, width=50)
    folder_entry.insert(0, default_folder_name)
    folder_entry.pack()
    
    status_label = tk.Label(root, text="Ready")
    status_label.pack()
    
    def startDownload():
        url = url_entry.get()
        if not url:
            messagebox.showerror("Error", "Please enter a URL")
            return
        
        user_folder_name = folder_entry.get().strip()
        if not user_folder_name:
            # If folder name is empty, generate a new timestamped name
            user_folder_name = f"TIFF_Downloads_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        save_dir = chooseSaveDirectory(root)
        if not save_dir:
            return
        
        start_button.config(state=tk.DISABLED)
        setStatus("Starting download...")
        
        download_thread = threading.Thread(target=performDownload, args=(url, save_dir, user_folder_name, root))
        download_thread.start()
    
    start_button = tk.Button(root, text="Start Download", command=startDownload)
    start_button.pack()
    
    root.mainloop()