import pdfplumber
import re
import json
import os

def debug_script_structure(pdf_path, num_pages=2):
    """Debug function to see the actual structure of the PDF."""
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages[:num_pages]):
            print(f"\n=== PAGE {i+1} ===")
            text = page.extract_text()
            lines = text.split('\n')
            for j, line in enumerate(lines):
                if 'THREEPIO' in line:
                    print(f"{j:3d}: |{line}| (repr: {repr(line)})")

def process_movie_script(pdf_path, output_path):
    """
    Process a movie script PDF and extract labeled tokens for scenes, characters, and dialogue.
    
    Args:
        pdf_path: Path to the PDF file
        output_path: Path to save the processed output
    """
    # Extract all text from PDF
    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                full_text += page_text + "\n"
    
    # Split into lines and process
    lines = full_text.split('\n')
    processed_data = []
    current_scene = None
    current_character = None
    dialogue_buffer = []  # Buffer to collect multi-line dialogue
    in_dialogue_mode = False
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        if not stripped:  # Empty line signals end of dialogue block
            if in_dialogue_mode and dialogue_buffer:
                # Save accumulated dialogue
                processed_data.append({
                    'type': 'DIALOGUE',
                    'text': ' '.join(dialogue_buffer),
                    'scene': current_scene
                })
                dialogue_buffer = []
                in_dialogue_mode = False
                current_character = None
            continue
        
        # Check if it's a scene heading (starts with number or INT./EXT. and is all caps)
        if stripped.isupper() and len(stripped) > 5:
            # Flush any pending dialogue first
            if in_dialogue_mode and dialogue_buffer:
                processed_data.append({
                    'type': 'DIALOGUE',
                    'text': ' '.join(dialogue_buffer),
                    'scene': current_scene
                })
                dialogue_buffer = []
                in_dialogue_mode = False
                current_character = None
            
            # Check if it starts with a number (scene number)
            if re.match(r'^\d+', stripped):
                current_scene = stripped
                processed_data.append({
                    'type': 'SCENE',
                    'text': stripped
                })
                continue
            # Check if it's a location/scene heading (INT/EXT or very long uppercase)
            elif any(x in stripped for x in ['INT.', 'EXT.', 'INT/EXT']) or len(stripped) > 20:
                current_scene = stripped
                processed_data.append({
                    'type': 'SCENE',
                    'text': stripped
                })
                continue
        
        # Check if it's a character name (short, all caps, not a scene)
        # Remove (CONT'D) or (cont'd) - handle various apostrophe types
        clean_char = re.sub(r"\s*\([Cc][Oo][Nn][Tt][''\u2019]?[Dd]\)", '', stripped)
        clean_char = clean_char.strip()
        
        if clean_char.isupper() and len(clean_char) <= 30 and len(clean_char.split()) <= 4:
            # Additional checks to avoid false positives
            if not any(x in clean_char for x in ['INT.', 'EXT.', 'FADE', 'CUT TO', 'DISSOLVE', 'THE END']):
                # Flush any previous dialogue
                if in_dialogue_mode and dialogue_buffer:
                    processed_data.append({
                        'type': 'DIALOGUE',
                        'text': ' '.join(dialogue_buffer),
                        'scene': current_scene
                    })
                    dialogue_buffer = []
                
                current_character = clean_char
                processed_data.append({
                    'type': 'CHARACTER',
                    'text': clean_char,
                    'scene': current_scene
                })
                in_dialogue_mode = True
                continue
        
        # Process dialogue or action
        if in_dialogue_mode and current_character:
            # Check if this line looks like action (starts with lowercase after dialogue)
            # In scripts, dialogue is typically indented/centered, action starts at margin
            # Also check if line starts with common action indicators
            if (line and not line[0].isspace() and len(line) > 50) or \
               any(stripped.lower().startswith(word) for word in ['the ', 'a ', 'an ', 'he ', 'she ', 'they ', 'it ', 'as ', 'suddenly ']):
                # This looks like action, not dialogue - flush dialogue and switch modes
                if dialogue_buffer:
                    processed_data.append({
                        'type': 'DIALOGUE',
                        'text': ' '.join(dialogue_buffer),
                        'scene': current_scene
                    })
                    dialogue_buffer = []
                in_dialogue_mode = False
                current_character = None
                processed_data.append({
                    'type': 'ACTION',
                    'text': stripped,
                    'scene': current_scene
                })
            else:
                # This is dialogue - add to buffer
                dialogue_buffer.append(stripped)
        else:
            # This is action/description
            processed_data.append({
                'type': 'ACTION',
                'text': stripped,
                'scene': current_scene
            })
    
    # Flush any remaining dialogue
    if in_dialogue_mode and dialogue_buffer:
        processed_data.append({
            'type': 'DIALOGUE',
            'text': ' '.join(dialogue_buffer),
            'scene': current_scene
        })
    
    # Consolidate consecutive ACTION entries into paragraphs
    consolidated_data = []
    action_buffer = []
    current_action_scene = None
    
    for item in processed_data:
        if item['type'] == 'ACTION':
            # Add to action buffer if same scene
            if current_action_scene == item.get('scene'):
                action_buffer.append(item['text'])
            else:
                # Flush previous action buffer if exists
                if action_buffer:
                    consolidated_data.append({
                        'type': 'ACTION',
                        'text': ' '.join(action_buffer),
                        'scene': current_action_scene
                    })
                # Start new action buffer
                action_buffer = [item['text']]
                current_action_scene = item.get('scene')
        else:
            # Flush action buffer when we hit non-action
            if action_buffer:
                consolidated_data.append({
                    'type': 'ACTION',
                    'text': ' '.join(action_buffer),
                    'scene': current_action_scene
                })
                action_buffer = []
                current_action_scene = None
            consolidated_data.append(item)
    
    # Flush any remaining actions
    if action_buffer:
        consolidated_data.append({
            'type': 'ACTION',
            'text': ' '.join(action_buffer),
            'scene': current_action_scene
        })
    
    processed_data = consolidated_data
    
    # Create output directory if it doesn't exist
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Save to file
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(processed_data, f, indent=2, ensure_ascii=False)
    
    # Also save a human-readable version
    txt_output = output_path.replace('.json', '.txt')
    with open(txt_output, 'w', encoding='utf-8') as f:
        for item in processed_data:
            if item['type'] == 'SCENE':
                f.write(f"\n[SCENE] {item['text']}\n")
            elif item['type'] == 'CHARACTER':
                f.write(f"\n[CHARACTER:{item['text']}]\n")
            elif item['type'] == 'DIALOGUE':
                f.write(f"[DIALOGUE] {item['text']}\n")
            elif item['type'] == 'ACTION':
                f.write(f"[ACTION] {item['text']}\n")
    
    return processed_data

# Process the script
if __name__ == "__main__":
    input_pdf = "scripts/star-wars-episode-iv-a-new-hope-1977.pdf"
    output_file = "processed_scripts/star_wars_processed.json"
    
    # Uncomment to debug structure
    # debug_script_structure(input_pdf, num_pages=1)
    
    print("Processing movie script...")
    data = process_movie_script(input_pdf, output_file)
    print(f"Processed {len(data)} elements")
    print(f"Output saved to {output_file} and corresponding .txt file")