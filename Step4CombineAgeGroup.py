import tkinter as tk
from tkinter import filedialog, messagebox
import pandas as pd

# Global DataFrame
df = None

def load_csv():
    """Load the input CSV file into the global DataFrame."""
    global df
    path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
    if path:
        try:
            df = pd.read_csv(path)
            entry_input.delete(0, tk.END)
            entry_input.insert(0, path)
            messagebox.showinfo("Info", "CSV file loaded successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load CSV: {e}")

def add_sum_columns():
    """Add sum column(s) for the specified age range and gender."""
    global df
    if df is None:
        messagebox.showerror("Error", "Please load a CSV file first.")
        return
    try:
        lower_age = int(entry_lower.get())
        upper_age = int(entry_upper.get())
    except ValueError:
        messagebox.showerror("Error", "Lower age and upper age must be integers.")
        return
    if lower_age >= upper_age:
        messagebox.showerror("Error", "Lower age must be less than upper age.")
        return
    gender = var_gender.get()
    
    # Determine prefixes based on gender
    if gender == 'female':
        prefixes = ['f_']
    elif gender == 'male':
        prefixes = ['m_']
    else:
        prefixes = ['f_', 'm_']
    
    # Calculate sum for each prefix
    for prefix in prefixes:
        cols = [col for col in df.columns if col.startswith(prefix)]
        sum_cols = []
        for col in cols:
            try:
                age = int(col[len(prefix):])
                if lower_age <= age < upper_age:
                    sum_cols.append(col)
            except ValueError:
                continue  # Skip columns with non-integer age
        if sum_cols:
            # Calculate sum
            sum_series = df[sum_cols].sum(axis=1)
            # Create new column name
            new_col_name = f"{prefix[:-1]}_{lower_age}_to_{upper_age}_sum"
            # Add new column
            df[new_col_name] = sum_series
            # Show included ages
            included_ages = [int(col[len(prefix):]) for col in sum_cols]
            message = (f"Added sum for {prefix[:-1]} ages: {', '.join(map(str, included_ages))}\n"
                       f"Note: The result will not include the value of {upper_age}.")
            messagebox.showinfo("Info", message)
        else:
            messagebox.showwarning("Warning", f"No columns found for {prefix[:-1]} in range {lower_age} to {upper_age}.")
    
    # Prompt user to add another or save
    response = messagebox.askyesno("Continue", "Do you want to add another sum?", icon='question')
    if response:
        # Clear inputs for next entry
        entry_lower.delete(0, tk.END)
        entry_upper.delete(0, tk.END)
        var_gender.set("both")
    else:
        save_file()

def save_file():
    """Save the current DataFrame to a CSV file."""
    global df
    if df is None:
        messagebox.showerror("Error", "No data to save. Please load a CSV file first.")
        return
    output_path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
    if output_path:
        df.to_csv(output_path, index=False)
        messagebox.showinfo("Success", f"Updated CSV saved to {output_path}")
    else:
        messagebox.showwarning("Warning", "No output path selected.")

# Create GUI
root = tk.Tk()
root.title("Add Age Group Sums")

# Input CSV
label_input = tk.Label(root, text="Input CSV:")
label_input.grid(row=0, column=0, padx=5, pady=5)
entry_input = tk.Entry(root, width=50)
entry_input.grid(row=0, column=1, padx=5, pady=5)
button_load = tk.Button(root, text="Load CSV", command=load_csv)
button_load.grid(row=0, column=2, padx=5, pady=5)

# Lower age
label_lower = tk.Label(root, text="Lower age:")
label_lower.grid(row=1, column=0, padx=5, pady=5)
entry_lower = tk.Entry(root)
entry_lower.grid(row=1, column=1, padx=5, pady=5)

# Upper age
label_upper = tk.Label(root, text="Upper age:")
label_upper.grid(row=2, column=0, padx=5, pady=5)
entry_upper = tk.Entry(root)
entry_upper.grid(row=2, column=1, padx=5, pady=5)

# Gender selection
var_gender = tk.StringVar(value="both")
radio_female = tk.Radiobutton(root, text="Female", variable=var_gender, value="female")
radio_female.grid(row=3, column=0, padx=5, pady=5)
radio_male = tk.Radiobutton(root, text="Male", variable=var_gender, value="male")
radio_male.grid(row=3, column=1, padx=5, pady=5)
radio_both = tk.Radiobutton(root, text="Both", variable=var_gender, value="both")
radio_both.grid(row=3, column=2, padx=5, pady=5)

# Add sum column button
button_add = tk.Button(root, text="Add Sum Column(s)", command=add_sum_columns)
button_add.grid(row=4, column=0, columnspan=3, padx=5, pady=5)

# Save file button
button_save = tk.Button(root, text="Save File", command=save_file)
button_save.grid(row=5, column=0, columnspan=3, padx=5, pady=5)

# Instruction label
label_instruction = tk.Label(root, text="You can add multiple sum columns before saving.")
label_instruction.grid(row=6, column=0, columnspan=3, padx=5, pady=5)

root.mainloop()