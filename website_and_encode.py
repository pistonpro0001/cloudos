import os
import requests
from bs4 import BeautifulSoup

# ==========================================
# ALPHABET LOADING & ENCODING
# ==========================================

def load_alphabet_from_file(file_path: str = "alphabet.txt") -> list:
    """
    Reads alphabet.txt line-by-line.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(
            f"Could not find '{file_path}'. Please make sure it's in the same folder as this script!"
        )
        
    alphabet_list = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            char = line.replace("\n", "").replace("\r", "")
            alphabet_list.append(char)
            
    return alphabet_list

try:
    ALPHABET = load_alphabet_from_file("alphabet.txt")
except FileNotFoundError as e:
    print(f"Warning: {e}")
    print("Falling back to internal string representation...")
    ALPHABET = [""] * 9 + list(r"`1234567890-=~!@#$%^&*()_+qwertyuiop[]\{}|asdfghjkl;':zxcvbnm,. /<>?}")


def encode_string_to_numbers(text: str) -> str:
    """
    Encodes a text string into a 2-digit numeric string using Scratch 1-indexed logic.
    """
    encoded_output = ""
    for char in text.lower():
        try:
            scratch_index = ALPHABET.index(char) + 1
            encoded_output += f"{scratch_index:02d}"
        except ValueError:
            encoded_output += "00"
    return encoded_output


# ==========================================
# HTML CLEANING
# ==========================================

def super_dumb_down_html(raw_html: str) -> str:
    """
    Filters raw HTML down to core text elements and strips all attributes.
    """
    soup = BeautifulSoup(raw_html, "html.parser")
    allowed_tags = {'title', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'b', 'strong', 'em', 'i', 'br', 'small'}
    
    for tag in soup.find_all(True):
        if tag.name not in allowed_tags:
            if tag.name in ['html', 'body', 'div', 'span', 'section', 'article', 'main', 'header', 'footer']:
                tag.unwrap()
            else:
                tag.decompose()
        else:
            tag.attrs = {}
            
    clean_elements = [str(tag).strip().lower() for tag in soup.find_all(allowed_tags)]
    return "\n".join(clean_elements).strip()


# ==========================================
# MAIN
# ==========================================

def fetch_clean_and_encode(url: str, htm_num: int = 5) -> dict:
    """
    The main function: Fetches a website, strips down its HTML, checks lengths,
    encodes to digits, and chunks into 5 Scratch-ready variables.
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        cleaned_text = super_dumb_down_html(response.text)
    except requests.exceptions.RequestException:
        cleaned_text = ""

    if not cleaned_text:
        cleaned_text = "<h1>nothing found at this url!</h1>"

    max_chars = 128 * htm_num
    if len(cleaned_text) > max_chars:
        cleaned_text = cleaned_text[:max_chars - 3] + "..."

    numeric_string = encode_string_to_numbers(cleaned_text)

    chunk_size = 256
    chunks = [numeric_string[i:i + chunk_size] for i in range(0, len(numeric_string), chunk_size)]
    
    scratch_vars = {}
    for i in range(1, htm_num + 1):
        if (i - 1) < len(chunks):
            scratch_vars[f"htm_{i}"] = chunks[i - 1]
        else:
            scratch_vars[f"htm_{i}"] = ""
            
    return scratch_vars

def decode_numbers_to_string(numeric_string: str) -> str:
    """
    Takes a 2-digit numeric string and converts it back into text
    """
    decoded_output = ""
    numeric_string = str(numeric_string)
    
    for i in range(0, len(numeric_string), 2):
        two_digit_pair = numeric_string[i:i+2]
        
        try:
            scratch_index = int(two_digit_pair)
            
            if scratch_index == 0:
                decoded_output += "?" 
                continue
                
            python_index = scratch_index - 1
            
            decoded_output += ALPHABET[python_index]
            
        except (ValueError, IndexError):
            decoded_output += "?"
            
    return decoded_output


# ==========================================
# EXAMPLE
# ==========================================
if __name__ == "__main__":
    target_url = "https://en.wikipedia.org/wiki/HTML"
    
    print(f"Processing: {target_url}...\n")
    scratch_payload = fetch_clean_and_encode(target_url)
    
    for var_name, numeric_data in scratch_payload.items():
        if not numeric_data:
            continue
            
        decoded_text = decode_numbers_to_string(numeric_data)
        
        print(f"{var_name} (Total digits: {len(numeric_data)}):")
        print(f"Encoded: '{numeric_data}'")
        print(f"Decoded: '{decoded_text}'")
        print("-" * 50)