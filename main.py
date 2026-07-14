import os
import subprocess
from tkinter import filedialog, Tk, Label, Button, Entry, StringVar, messagebox


def compress_files():
    file_path = file_var.get()
    if not file_path:
        messagebox.showerror("Error", "Please select a file to compress!")
        return

    save_path = save_var.get()
    if not save_path:
        messagebox.showerror("Error", "Please enter a save path!")
        return

    try:
        # Convert file paths to proper Windows format
        print("file_path : " + file_path)
        print("save_path : " + save_path)
        file_path = os.path.normpath(file_path)
        save_path = os.path.normpath(save_path)
        print("file_path1 : " + file_path)
        print("save_path2 : " + save_path)


        # Step 1: Precomp
        print(f"Running Precomp on {file_path}...")
        precomp_command = [r"C:\Program Files\precomp\windows\precomp.exe", "-v", rf"-o{save_path}.precomp.bin", file_path]
        # result = subprocess.run(precomp_command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # result = subprocess.run(precomp_command, check=False)
        subprocess.run(precomp_command, check=False)
        # if result.returncode != 0:
        #     print(result.stderr.decode())
        #     raise subprocess.CalledProcessError(result.returncode, precomp_command)
        print(f"Precomp completed: {save_path}.precomp.bin")

        # Step 2: SREP
        print(f"Running SREP on {save_path}.precomp.bin...")
        srep_command = [r"C:\Program Files\srep\srep64.exe", "-m3f", f"{save_path}.precomp.bin", f"{save_path}.srep"]
        # result = subprocess.run(srep_command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        result = subprocess.run(srep_command, check=False)
        if result.returncode != 0:
            print(result.stderr.decode())
            raise subprocess.CalledProcessError(result.returncode, srep_command)
        print(f"SREP completed: {save_path}.srep")

        # Step 3: FreeArc
        print(f"Running FreeArc on {save_path}.srep...")
        arc_command = [r"C:\Program Files (x86)\FreeArc\bin\arc.exe", "a", "-max", f"{save_path}.arc", f"{save_path}.srep"]
        # result = subprocess.run(arc_command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        result = subprocess.run(arc_command, check=False)
        if result.returncode != 0:
            print(result.stderr.decode())
            raise subprocess.CalledProcessError(result.returncode, arc_command)
        print(f"FreeArc compression completed: {save_path}.arc")

        messagebox.showinfo("Success", "Compression completed successfully!")

    except subprocess.CalledProcessError as e:
        messagebox.showerror("Error", f"Compression failed: {e}")
        print(f"Compression failed: {e}")
        return


def uncompress_files():
    file_path = uncompress_file_var.get()
    if not file_path:
        messagebox.showerror("Error", "Please select a file to uncompress!")
        return

    save_path = uncompress_save_var.get()
    if not save_path:
        messagebox.showerror("Error", "Please enter a save path!")
        return

    try:
        # Convert file paths to proper Windows format
        file_path = os.path.normpath(file_path)
        save_path = os.path.normpath(save_path)

        # Step 1: FreeArc
        print(f"Running FreeArc to uncompress {file_path}...")
        arc_command = [r"C:\Program Files (x86)\FreeArc\bin\arc.exe", "x", file_path, "-o", save_path]
        result = subprocess.run(arc_command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            print(result.stderr.decode())
            raise subprocess.CalledProcessError(result.returncode, arc_command)
        print(f"Uncompression completed: {save_path}")
        messagebox.showinfo("Success", "Uncompression completed successfully!")

    except subprocess.CalledProcessError as e:
        messagebox.showerror("Error", f"Uncompression failed: {e}")
        print(f"Uncompression failed: {e}")
        return


def select_file():
    file_path = filedialog.askopenfilename(title="Select a file to compress")
    file_var.set(file_path)


def select_uncompress_file():
    file_path = filedialog.askopenfilename(title="Select a file to uncompress")
    uncompress_file_var.set(file_path)


def create_gui():
    root = Tk()
    root.title("Extreme Compressor")

    # Variables for compression
    global file_var, save_var
    file_var = StringVar()
    save_var = StringVar()

    # Variables for uncompression
    global uncompress_file_var, uncompress_save_var
    uncompress_file_var = StringVar()
    uncompress_save_var = StringVar()

    # Compression section
    Label(root, text="Select File to Compress:").grid(row=0, column=0, padx=10, pady=10)
    Entry(root, textvariable=file_var, width=50).grid(row=0, column=1, padx=10, pady=10)
    Button(root, text="Browse", command=select_file).grid(row=0, column=2, padx=10, pady=10)

    Label(root, text="Save As:").grid(row=1, column=0, padx=10, pady=10)
    Entry(root, textvariable=save_var, width=50).grid(row=1, column=1, padx=10, pady=10)

    Button(root, text="Start Compression", command=compress_files).grid(row=2, columnspan=3, pady=20)

    # Uncompression section
    Label(root, text="Select File to Uncompress:").grid(row=3, column=0, padx=10, pady=10)
    Entry(root, textvariable=uncompress_file_var, width=50).grid(row=3, column=1, padx=10, pady=10)
    Button(root, text="Browse", command=select_uncompress_file).grid(row=3, column=2, padx=10, pady=10)

    Label(root, text="Output Path:").grid(row=4, column=0, padx=10, pady=10)
    Entry(root, textvariable=uncompress_save_var, width=50).grid(row=4, column=1, padx=10, pady=10)

    Button(root, text="Start Uncompression", command=uncompress_files).grid(row=5, columnspan=3, pady=20)

    root.mainloop()


if __name__ == "__main__":
    create_gui()
