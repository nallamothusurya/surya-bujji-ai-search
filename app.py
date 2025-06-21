import re
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold, GenerationConfig # Added GenerationConfig
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, render_template
from markupsafe import Markup
import json
import markdown2
import traceback # For detailed error logging

app = Flask(__name__)
try:
    # User's provided API key
    api_key ="AIzaSyBjTaPSaavhmAVFOEUY9lS6x2mw8ikkaUU" # Replace with your actual key if needed
    genai.configure(api_key=api_key)
    # Using a known latest model for broader compatibility, adjust if 'gemini-2.0-flash' is specifically required and available
    model = genai.GenerativeModel('gemini-2.0-flash') # 
except Exception as e:
    tb_str = traceback.format_exc()
    print(f"FATAL ERROR: Could not configure or initialize Gemini API. Exception Type: {type(e)}, Error: {e}\nTraceback:\n{tb_str}")
    model = None 

# --- Core Helper Functions ---
def get_best_image_url(search_query: str, image_index_to_fetch: int = 0) -> str | None:
    """
    Fetches an image URL from Bing based on the search query and the desired image index.
    """
    if not search_query:
        print("WARNING: Empty search query provided to get_best_image_url.")
        return None

    print(f"INFO: Attempting to find image (index {image_index_to_fetch}) for query: '{search_query}'")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
    encoded_query = requests.utils.quote(search_query)
    url = f"https://www.bing.com/images/search?q={encoded_query}&form=HDRSC2"

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        image_elements = soup.find_all("a", {"class": "iusc"})

        if not image_elements:
            print(f"INFO: No 'iusc' image elements found on Bing for query '{search_query}'. Trying fallback.")
            img_tags = soup.find_all('img', {'src': re.compile(r'^https?://')})
            if image_index_to_fetch < len(img_tags):
                img_tag = img_tags[image_index_to_fetch]
                src = img_tag.get('src')
                # Basic filter for meaningful images (size might not always be available)
                if src and not any(x in src for x in ['logo', 'icon', 'svg', 'spinner', 'loader', 'avatar']):
                     # Check if it's a data URI (less likely for primary images but good to filter)
                    if not src.startswith('data:image'):
                        print(f"SUCCESS (fallback img tag, index {image_index_to_fetch}): Found image for query '{search_query}': {src[:70]}...")
                        return src
            print(f"FAILURE: Fallback img tag search also failed or index out of bounds for query '{search_query}'.")
            return None

        if image_index_to_fetch < len(image_elements):
            target_element = image_elements[image_index_to_fetch]
            m_data = target_element.get("m")
            if m_data:
                try:
                    m_json = json.loads(m_data)
                    image_url = m_json.get("murl")
                    if image_url:
                        print(f"SUCCESS: Found image (index {image_index_to_fetch}) for query '{search_query}': {image_url[:70]}...")
                        return image_url
                except json.JSONDecodeError:
                    print(f"WARNING: Could not parse 'm' attribute JSON for image element at index {image_index_to_fetch} for query '{search_query}'.")
        else:
            print(f"WARNING: Requested image index {image_index_to_fetch} out of bounds. Found {len(image_elements)} 'iusc' elements for query '{search_query}'.")
        
        print(f"FAILURE: Could not extract URL for image at index {image_index_to_fetch} for query '{search_query}' using 'iusc' elements.")
        return None

    except requests.exceptions.RequestException as e:
        print(f"WARNING: Request failed for Bing Image Search ('{search_query}'). Error: {e}")
    except Exception as e:
        print(f"WARNING: An unexpected error occurred while processing Bing Image Search ('{search_query}'). Error: {e}")
    return None

def generate_explanation(prompt: str) -> str:
    """
    Generates the main explanation from Gemini, asking it to place [IMAGE] placeholders.
    """
    if not model:
        return "Error: AI model is not configured. Please check server logs."

    engineered_prompt = f"""
    Explain the topic: "{prompt}".

    Your Core Directives:
    1.  Explanation Style: Be concise but thorough. Give "gunshot" explanations—powerful, direct, and to the point.
    2.  Structure: Use Markdown. Start with a main H1 title for the topic. Use H2 or H3 for sub-topics.
    3.  Autonomous Image Placement: As an expert educator, strategically decide where visual aids are needed most. 
        For each desired image, insert a simple placeholder on its own line: `[IMAGE]`
        Place these `[IMAGE]` placeholders typically after a paragraph or section that would benefit from a visual. Ensure `[IMAGE]` is on its own line.
    4.Give exact user asked interested topic content beautifully even if it bad also.

    EXAMPLE of your required output structure:
    # Main Topic Title (e.g., Photosynthesis)
    Some introductory text about the main topic.

    [IMAGE]

    ## Sub-topic A (e.g., Light-Dependent Reactions)
    Explanation for sub-topic A.

    [IMAGE]

    More text for sub-topic A.

    ## Sub-topic B (e.g., Calvin Cycle)
    Explanation for sub-topic B.

    [IMAGE]

    ---
    Now, generate the complete response for my topic: "{prompt}"
    """
    print("INFO: Sending main explanation prompt to Gemini API...")
    try:
        safety_configurations = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
        
        response = model.generate_content(
            engineered_prompt, 
            safety_settings=safety_configurations
        )
        
        ai_text = None
        if hasattr(response, 'text'):
            ai_text = response.text
        elif response.parts:
            ai_text = "".join(part.text for part in response.parts if hasattr(part, 'text'))
        
        if ai_text:
            print("INFO: Received structured response from Gemini for main explanation.")
            return ai_text
        else:
            # Handle cases where response.text is None but there might be blocking info
            candidate_info = ""
            if response.candidates:
                candidate = response.candidates[0] # Assuming one candidate
                finish_reason_name = candidate.finish_reason.name if hasattr(candidate.finish_reason, 'name') else "UNKNOWN"
                candidate_info = f" Candidate Finish Reason: {finish_reason_name}."
                if finish_reason_name == "SAFETY" and hasattr(candidate, 'safety_ratings'):
                    safety_ratings_info = " Safety Ratings: " + ", ".join([f"{rating.category.name}: {rating.probability.name}" for rating in candidate.safety_ratings])
                    candidate_info += safety_ratings_info
            
            prompt_feedback_info = ""
            if response.prompt_feedback and response.prompt_feedback.block_reason:
                prompt_feedback_info = f" Prompt Feedback Block Reason: {response.prompt_feedback.block_reason.name}."

            error_message = f"Error: AI model returned an empty explanation. This might be due to content policies or an issue with the response structure.{candidate_info}{prompt_feedback_info} Please try rephrasing your prompt or check server logs. Full Response: {response}"
            print(f"ERROR: {error_message}")
            return error_message

    except Exception as e:
        tb_str = traceback.format_exc()
        error_message_detail = str(e)
        if hasattr(e, 'message') and e.message:
            error_message_detail = f"API Error: {e.message} (Underlying exception: {str(e)})"
        
        print(f"ERROR: Failed to call Gemini API for main explanation. Exception Type: {type(e)}, Error Details: {error_message_detail}\nTraceback:\n{tb_str}")
        
        user_error = "Error: Could not retrieve an explanation from the AI model."
        lower_error_detail = error_message_detail.lower()
        if "safety" in lower_error_detail or \
           "block_reason" in lower_error_detail or \
           "invalid argument" in lower_error_detail or \
           isinstance(e, (getattr(genai.types, 'BlockedPromptException', type(None)), 
                          getattr(genai.types, 'StopCandidateException', type(None)))) or \
           (hasattr(e, 'grpc_status_code') and e.grpc_status_code == 3):
            user_error += " This may be due to the prompt violating content policies or an API configuration issue. Please check server logs for details."
        else:
            user_error += " This could be related to API key, model name, network connectivity, or other server-side issues. Check server logs."
        return user_error

def generate_image_search_query(heading: str, context_text: str, original_topic: str) -> str:
    """
    Generates a Bing image search query using Gemini based on heading and context.
    """
    if not model:
        print("WARNING: AI model not configured. Cannot generate image search query. Falling back to heading.")
        return heading if heading else original_topic

    # Clean and shorten context_text for the image query prompt
    cleaned_context = re.sub(r'#+\s*', '', context_text) # Remove markdown from context
    cleaned_context = re.sub(r'\s+', ' ', cleaned_context).strip() # Normalize whitespace
    max_context_len = 250 # Characters for context snippet
    if len(cleaned_context) > max_context_len:
        cleaned_context = cleaned_context[:max_context_len] + "..."

    prompt_for_image_query = f"""
    The main topic is: "{original_topic}".
    The current section heading is: "{heading}".
    The text immediately preceding the need for an image is:
    ---
    {cleaned_context}
    ---
    Based on this heading and text, generate a concise and effective Bing image search query (ideally 3-7 words) to find a highly relevant illustrative image for this specific section.
    Focus on the key nouns, concepts, or visual elements described or implied.
    Output ONLY the search query itself, with no extra explanations, labels, or quotation marks.

    Example:
    If heading is "Cellular Respiration Stages" and text mentions "Glycolysis breaking down glucose", a good query might be: "glycolysis glucose breakdown diagram"

    Generate the image search query:
    """
    print(f"INFO: Sending image query generation prompt to Gemini. Original Topic: '{original_topic}', Heading: '{heading}', Context Snippet: '{cleaned_context[:60]}...'")
    try:
        safety_configurations = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
        # Configure generation for short, direct output
        generation_config = GenerationConfig(
            temperature=0.4, # More focused output
            max_output_tokens=20, # Limit query length
            # top_p=0.9, # Alternative to temperature
            # top_k=10   # Alternative to temperature
        )

        response = model.generate_content(
            prompt_for_image_query,
            safety_settings=safety_configurations,
            generation_config=generation_config
        )
        
        query_text = None
        if hasattr(response, 'text'):
            query_text = response.text
        elif response.parts:
            query_text = "".join(part.text for part in response.parts if hasattr(part, 'text'))

        if query_text:
            # Clean up the query: remove potential "Query:" prefixes, quotes, newlines
            query_text = re.sub(r'^(Search Query:|Query:)\s*', '', query_text, flags=re.IGNORECASE).strip()
            query_text = query_text.strip('"\'').strip() # Remove surrounding quotes and whitespace
            if query_text:
                 print(f"SUCCESS: Gemini generated image query: '{query_text}'")
                 return query_text
            else: # AI returned empty string after cleaning
                print(f"WARNING: Gemini generated an empty image query after cleaning. Falling back. Heading: '{heading}'")
                return heading if heading else original_topic
        else:
            print(f"WARNING: Gemini returned empty or no text for image query. Response: {response}. Falling back to heading: '{heading}'")
            return heading if heading else original_topic
    except Exception as e:
        tb_str = traceback.format_exc()
        print(f"ERROR: Failed to call Gemini API for image query generation. Error: {e}\nTraceback:{tb_str}\nFalling back to heading: '{heading}'")
        return heading if heading else original_topic

@app.route('/', methods=['GET'])
def index():
    if not model: 
        return render_template('index.html', error="AI Service Error: The AI model could not be initialized. Please contact the administrator.")
    return render_template('index.html')

@app.route('/prepare', methods=['POST'])
def prepare():
    if not model: 
        return render_template('index.html', error="AI Service Error: The AI model is not available. Please try again later or contact the administrator.")

    user_prompt = request.form.get('prompt')
    if not user_prompt:
        return render_template('index.html', error="Please enter a topic.")

    gemini_response_text = generate_explanation(user_prompt)
    if gemini_response_text.startswith("Error:"):
        return render_template('index.html', error=gemini_response_text, prompt=user_prompt)
    
    # Split by [IMAGE] placeholder, keeping the placeholder as a delimiter
    content_parts = re.split(r'(\[IMAGE\])', gemini_response_text)
    
    final_html_content = ""
    
    active_heading_text = user_prompt # Default heading is the user's initial prompt
    active_heading_level = 0
    first_h1_text = None 
    main_image_url = None 
    processed_first_h1_image = False 

    heading_regex = re.compile(r"^\s*(#{1,6})\s*(.+?)\s*(?:#\s*)*$", re.MULTILINE)
    image_counter_for_subheadings = 0 # Used to vary image index for non-H1 images

    for i, part in enumerate(content_parts):
        if not part.strip(): # Skip empty or whitespace-only parts
            continue

        if part == '[IMAGE]':
            # This is an image placeholder.
            # The context text is content_parts[i-1] (the text segment before this [IMAGE]).
            preceding_text_segment = ""
            if i > 0 and content_parts[i-1] != '[IMAGE]':
                preceding_text_segment = content_parts[i-1]
            
            # Generate the AI-powered search query for Bing
            ai_generated_bing_query = generate_image_search_query(
                heading=active_heading_text, 
                context_text=preceding_text_segment,
                original_topic=user_prompt 
            )
            
            query_for_bing = ai_generated_bing_query # Use the AI generated query
            alt_text_description = active_heading_text # Base for alt text

            image_url_to_display = None
            image_fetch_index = 0 # Default index for fetching

            # Determine if this image is for the main H1 title
            is_main_h1_image_context = (active_heading_level == 1 and 
                                        active_heading_text == first_h1_text and 
                                        not processed_first_h1_image)

            if is_main_h1_image_context:
                alt_text = f"Main illustration for {first_h1_text}, based on query: {query_for_bing}"
                print(f"INFO: Fetching MAIN image (AI query: '{query_for_bing}') for H1: '{first_h1_text}'")
                image_url_to_display = get_best_image_url(query_for_bing, image_index_to_fetch=0)
                if image_url_to_display:
                    main_image_url = image_url_to_display 
                    processed_first_h1_image = True
            else: 
                context_prefix_for_alt = first_h1_text if first_h1_text else user_prompt
                alt_text = f"Visual for '{alt_text_description}' (related to {context_prefix_for_alt}), AI query: '{query_for_bing}'"
                
                print(f"INFO: Fetching SUB image (AI query: '{query_for_bing}') for heading '{active_heading_text}'")
                
                image_fetch_index = image_counter_for_subheadings 
                image_url_to_display = get_best_image_url(query_for_bing, image_index_to_fetch=image_fetch_index)

                # Deduplication: if sub-image is same as main, try next one
                if image_url_to_display and main_image_url and image_url_to_display == main_image_url:
                    print(f"INFO: Sub-image (AI query: '{query_for_bing}', index {image_fetch_index}) matched main image. Attempting next.")
                    image_fetch_index += 1
                    second_attempt_url = get_best_image_url(query_for_bing, image_index_to_fetch=image_fetch_index)
                    if second_attempt_url and second_attempt_url != main_image_url:
                        image_url_to_display = second_attempt_url
                        print(f"SUCCESS: Fetched unique SUB image (index {image_fetch_index}): {second_attempt_url[:70]}...")
                    else:
                        print(f"WARNING: Could not fetch a unique different SUB image (index {image_fetch_index}) for '{query_for_bing}'. Using first found or it was also a duplicate.")
                
                if image_url_to_display: # If an image was successfully fetched (either first or second attempt)
                    image_counter_for_subheadings = image_fetch_index + 1 # Next non-H1 image should try a new index

            # Append image HTML or error message
            if image_url_to_display:
                safe_alt_text = Markup.escape(alt_text)
                image_html = f'<div class="image-container"><img src="{image_url_to_display}" alt="{safe_alt_text}" loading="lazy"></div>'
                final_html_content += image_html
            else:
                error_query_display = Markup.escape(query_for_bing)
                final_html_content += f'<p class="image-error"><em>[Could not load image for AI-generated query: "{error_query_display}"]</em></p>'

        else: # This part is a text segment
            text_segment = part
            
            # Find the last heading in this segment to update active_heading_text
            # This active_heading_text will be used as context for the *next* [IMAGE] tag
            headings_in_segment = heading_regex.findall(text_segment)
            if headings_in_segment:
                # The last heading in a segment is the most current one
                last_heading_hashes, last_heading_text_content = headings_in_segment[-1]
                active_heading_text = last_heading_text_content.strip()
                active_heading_level = len(last_heading_hashes)
                
                print(f"DEBUG: Active heading updated to (L{active_heading_level}): '{active_heading_text}' from text segment.")

                if not first_h1_text and active_heading_level == 1:
                    first_h1_text = active_heading_text
                    print(f"DEBUG: Set first_h1_text to: '{first_h1_text}'")
            # If no heading in this segment, active_heading_text and active_heading_level remain from previous segment or default.
            
            final_html_content += markdown2.markdown(text_segment, extras=["fenced-code-blocks", "tables", "cuddled-lists", "smarty-pants"])
    
    safe_html_output = Markup(final_html_content)
    return render_template('index.html', result=safe_html_output, prompt=user_prompt)

if __name__ == '__main__':
    if not model:
        print("CRITICAL: AI Model failed to initialize. The application might not function correctly.")
    app.run(debug=True, threaded=True)