1. Install `venv` if necessary:

   ```bash
   sudo apt install python3-venv
   ```

2. Create a virtual environment:

   ```bash
   git clone https://github.com/arevindh/tinxy-local

   cd tinxy-local

   python3 -m venv venv
   ```

3. Activate the virtual environment:

   ```bash
   source venv/bin/activate
   ```

4. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

5. Run the script

   ```bash
   python discover.py
   ```

6. Enter the Bearer Token

   The script will prompt you for your Bearer token. Enter it when prompted:

   ```plaintext
   Please enter your Bearer token: 
   ```

7. Deactivate the virtual environment when done:

   ```bash
   deactivate
   ```
