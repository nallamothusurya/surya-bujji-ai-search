import os
import re
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, render_template
from markupsafe import Markup
from dotenv import load_dotenv
import json
import markdown2

# --- Secure Configuration ---
load_dotenv()
app = Flask(__name__)

# --- CRITICAL SECURITY & MODEL CONFIGURATION ---
try:
    api_key ="AIzaSyDGvfbxLWR-l8hMQbgz5dPekXIDdm_44SY"
    if not api_key:
        raise KeyError
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')
except KeyError:
    print("="*80)
    print("FATAL ERROR: GEMINI_API_KEY not found or is empty in your .env file.")
    print("Please create a file named '.env' in the same directory as app.py and add:")
    print("GEMINI_API_KEY=YOUR_API_KEY_HERE")
    print("="*80)
    exit()

# --- NEW: Anti-Fragile Parsing Helper ---
def _parse_image_queries(placeholder_text: str) -> list:
    """
    Parses the image query list from Gemini's placeholder,
    healing common syntax errors to prevent crashes.
    """
    # 1. Extract the raw content inside [IMAGE: ...]
    raw_content = placeholder_text.strip()[7:-1].strip()
    
    # 2. First attempt: assume the content is perfect JSON
    try:
        queries = json.loads(raw_content)
        if isinstance(queries, list):
            return queries
    except json.JSONDecodeError:
        print(f"INFO: Initial JSON parse failed for content: {raw_content}. Attempting to heal.")

    # 3. Healing attempt: Common issue is a missing closing bracket.
    try:
        healed_content = raw_content
        if healed_content.startswith('[') and not healed_content.endswith(']'):
            healed_content += ']'
        
        queries = json.loads(healed_content)
        if isinstance(queries, list):
            print("SUCCESS: Healed JSON by adding closing bracket.")
            return queries
    except json.JSONDecodeError:
        print(f"INFO: Healing attempt failed. Proceeding to graceful fallback.")

    # 4. Graceful Fallback: Treat the entire raw content as a single query.
    # This removes brackets, quotes, etc., and uses the text inside.
    fallback_query = re.sub(r'[\[\]",]', '', raw_content).strip()
    print(f"WARNING: Using fallback search query: '{fallback_query}'")
    return [fallback_query] if fallback_query else []

# --- Core Helper Functions ---
def get_best_image_url(search_queries: list) -> str | None:
    # (This function remains unchanged)
    print(f"INFO: Attempting to find best image for queries: {search_queries}")
    for query in search_queries:
        if not query:
            continue
        # ... (rest of the function is identical to before)
        print(f"INFO: Trying query: '{query}'...")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
        encoded_query = requests.utils.quote(query)
        url = f"https://www.bing.com/images/search?q={encoded_query}&first=1"
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            image_element = soup.find("a", {"class": "iusc"})
            if image_element:
                m_data = image_element.get("m")
                if m_data:
                    m_json = json.loads(m_data)
                    image_url = m_json.get("murl")
                    if image_url:
                        print(f"SUCCESS: Found image for query '{query}': {image_url[:50]}...")
                        return image_url
        except Exception as e:
            print(f"WARNING: Request failed for query '{query}'. Error: {e}")
    print(f"FAILURE: Exhausted all queries. No image found for {search_queries}.")
    return None

def generate_explanation(prompt: str) -> str:
    """
    Generates a detailed explanation from Gemini, with stricter instructions for valid JSON.
    """
    # --- UPDATED & REINFORCED PROMPT ---
    engineered_prompt = f"""
    Explain the topic: "{prompt}".

    **Your Core Directives:**
    1.  **Explanation Style:** Be concise but thorough. Give "gunshot" explanations—powerful, direct, and to the point.
    2.  **Autonomous Image Placement:** As an expert educator, strategically decide where visual aids are needed most and their ideal placement.
    3.  **CRITICAL Image Placeholder Format:** For each image, you MUST provide a placeholder using this EXACT syntax: `[IMAGE: A_VALID_JSON_ARRAY_OF_STRINGS]`.
    4.  **JSON Requirements:** The JSON array MUST start with `[` and end with `]`. It must contain 3 comma-separated, double-quoted search queries.

    **PERFECT EXAMPLE of your required output structure:**
    # Topic
    Concise text.

    [IMAGE: ["best, most specific query", "good alternative query", "broad fallback query"]]

    ## Sub-topic
    More concise text.
    
    [IMAGE: ["second set of queries", "alternative for second query", "broad fallback for second query"]]

    ---
    Now, generate the complete response for my topic: "{prompt}"
    """
    print("INFO: Sending enhanced prompt to Gemini API...")
    try:
        response = model.generate_content(engineered_prompt, safety_settings={'HARASSMENT':'block_none'})
        print("INFO: Received structured response from Gemini.")
        return response.text
    except Exception as e:
        print(f"ERROR: Failed to call Gemini API. Error: {e}")
        return "Error: Could not retrieve an explanation from the AI model. Check API key, model name, and network."

# --- Flask Routes ---
@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/prepare', methods=['POST'])
def prepare():
    user_prompt = request.form.get('prompt')
    if not user_prompt:
        return render_template('index.html', error="Please enter a topic.")

    gemini_response = generate_explanation(user_prompt)
    
    parts = re.split(r'(\[IMAGE:.*?\])', gemini_response) # Adjusted regex slightly for robustness
    final_html_content = ""

    for part in parts:
        # Check for our specific placeholder format
        if part.startswith('[IMAGE:') and part.endswith(']'):
            # --- USE OUR NEW ANTI-FRAGILE PARSER ---
            search_queries = _parse_image_queries(part)
            
            if not search_queries:
                 final_html_content += f'<p class="image-error"><em>[AI Error: Malformed or empty image instruction.]</em></p>'
                 continue

            # Use our intelligent fetching engine
            best_image_url = get_best_image_url(search_queries)
            
            if best_image_url:
                alt_text = search_queries[0]
                image_html = f'<div class="image-container"><img src="{best_image_url}" alt="{alt_text}" loading="lazy"></div>'
                final_html_content += image_html
            else:
                final_html_content += f'<p class="image-error"><em>[Could not load image for: "{search_queries[0]}"]</em></p>'
        else:
            # Normal text part.
            final_html_content += markdown2.markdown(part, extras=["fenced-code-blocks", "tables", "cuddled-lists"])
            
    safe_html_output = Markup(final_html_content)
    return render_template('index.html', result=safe_html_output, prompt=user_prompt)

# --- Run the Application ---
if __name__ == '__main__':
    app.run(debug=True, threaded=True)