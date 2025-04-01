import streamlit as st
from utils.auth import (
    firebase_signup,
    firebase_login,
    is_authenticated,
    logout_user,
    get_current_user,
    get_firestore_db
)
from utils.processor import process_document, create_word_doc
import requests
import time
from datetime import datetime
import uuid
from firebase_admin import firestore
import subprocess

# Configure app
st.set_page_config(
    page_title="DocEnhancer AI",
    page_icon="✍️",
    layout="wide"
)

# Ollama configuration
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "deepseek-r1:7b"
MAX_RETRIES = 3
INITIAL_TIMEOUT = 30
TIMEOUT_BACKOFF_FACTOR = 2

def start_ollama_server():
    """Attempt to start Ollama server if not running"""
    try:
        subprocess.Popen(["ollama", "serve"], 
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
        time.sleep(3)  # Give it time to start
        return True
    except:
        return False

def check_ollama_connection():
    """Check if Ollama server is responsive"""
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        return response.status_code == 200
    except:
        # Try to restart if not running
        if not start_ollama_server():
            return False
        time.sleep(5)  # Additional wait time after restart attempt
        try:
            response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
            return response.status_code == 200
        except:
            return False

def enhance_text_with_ollama(text: str) -> str:
    """Robust Ollama API call with auto-retry and backoff"""
    timeout = INITIAL_TIMEOUT
    
    for attempt in range(MAX_RETRIES):
        try:
            if not check_ollama_connection():
                raise ConnectionError("Ollama server unavailable")
            
            response = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a professional editor. Improve this document while preserving its meaning:"
                        },
                        {
                            "role": "user",
                            "content": text[:20000]  # Limit input size
                        }
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "repeat_penalty": 1.1
                    }
                },
                timeout=timeout
            )
            response.raise_for_status()
            return response.json()["message"]["content"]
        
        except requests.exceptions.RequestException as e:
            if attempt == MAX_RETRIES - 1:
                raise  # Re-raise on final attempt
            time.sleep(timeout * 0.5)  # Wait before retry
            timeout *= TIMEOUT_BACKOFF_FACTOR  # Exponential backoff
            continue
        
        except Exception as e:
            st.error(f"Unexpected error: {str(e)}")
            return text
    
    return text  # Fallback return

def save_to_firestore(user_id, doc_name, original_content, enhanced_content):
    """Save document to Firestore with error handling"""
    try:
        db = get_firestore_db()
        doc_ref = db.collection("users").document(user_id).collection("documents").document()
        
        doc_ref.set({
            "doc_id": str(uuid.uuid4()),
            "name": doc_name,
            "original_content": original_content[:10000],
            "enhanced_content": enhanced_content[:10000],
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "status": "processed"
        })
        
        user_ref = db.collection("users").document(user_id)
        user_ref.update({"doc_count": firestore.Increment(1)})
        
        return doc_ref.id
    except Exception as e:
        st.error(f"Failed to save document: {str(e)}")
        return None

def render_sidebar():
    """Sidebar with connection status"""
    with st.sidebar:
        st.title("DocEnhancer")
        
        # Connection status
        if check_ollama_connection():
            st.success("🟢 Ollama Connected")
            if st.button("Test Ollama Response"):
                try:
                    test_response = requests.post(
                        f"{OLLAMA_URL}/api/chat",
                        json={
                            "model": OLLAMA_MODEL,
                            "messages": [{"role": "user", "content": "Hello"}],
                            "stream": False
                        },
                        timeout=10
                    )
                    st.success(f"Response time: {test_response.elapsed.total_seconds():.2f}s")
                except Exception as e:
                    st.error(f"Test failed: {str(e)}")
        else:
            st.error("🔴 Ollama Not Connected")
            if st.button("Attempt to Start Ollama"):
                if start_ollama_server():
                    st.rerun()
                else:
                    st.error("Failed to start Ollama server")
        
        if is_authenticated():
            user = get_current_user()
            st.success(f"Logged in as {user.display_name}")
            
            try:
                db = get_firestore_db()
                user_data = db.collection("users").document(user.uid).get().to_dict()
                if user_data and 'doc_count' in user_data:
                    st.info(f"Documents processed: {user_data['doc_count']}")
            except:
                pass
            
            if st.button("Logout"):
                logout_user()
                st.rerun()
        else:
            st.info("Please register or login")

def main():
    render_sidebar()
    
    if not is_authenticated():
        st.title("Welcome to Ai Doc Assistant")
        
        tab1, tab2 = st.tabs(["Login", "Register"])
        
        with tab1:
            with st.form("login_form"):
                email = st.text_input("Email")
                password = st.text_input("Password", type="password")
                if st.form_submit_button("Login"):
                    try:
                        user = firebase_login(email, password)
                        st.session_state.user = user
                        st.success("Login successful!")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
        
        with tab2:
            with st.form("register_form"):
                email = st.text_input("Email")
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                confirm_password = st.text_input("Confirm Password", type="password")
                if st.form_submit_button("Register"):
                    if password != confirm_password:
                        st.error("Passwords don't match!")
                    else:
                        try:
                            user = firebase_signup(email, password, username)
                            st.session_state.user = user
                            st.success("Registration successful! Please login")
                        except Exception as e:
                            st.error(str(e))
        return
    
    # Document processing
    st.title("✍️ Document Editor")
    
    if not check_ollama_connection():
        st.warning("""
        **Ollama server is not available.**
        - Make sure Ollama is installed and running
        - Try restarting the server: `ollama serve`
        - Check the terminal for errors
        """)
    
    uploaded_file = st.file_uploader(
        "Upload Document (TXT/PDF/DOCX)",
        type=['txt', 'pdf', 'docx']
    )
    
    if uploaded_file:
        try:
            with st.spinner("Extracting text..."):
                original_text = process_document(uploaded_file)
                file_key = uploaded_file.name.replace(".", "_")
            
            with st.expander("Original Document", expanded=True):
                st.text_area(
                    "Original Content",
                    value=original_text,
                    height=250,
                    key=f"original_{file_key}"
                )
            
            if st.button("✨ Enhance Document", 
                        key=f"enhance_{file_key}",
                        disabled=not check_ollama_connection()):
                with st.spinner("processing your document (this may take several minutes for large documents)..."):
                    try:
                        enhanced_text = enhance_text_with_ollama(original_text)
                        if enhanced_text and enhanced_text != original_text:
                            st.session_state.enhanced_text = enhanced_text
                            
                            user = get_current_user()
                            doc_id = save_to_firestore(
                                user.uid,
                                uploaded_file.name,
                                original_text,
                                enhanced_text
                            )
                            if doc_id:
                                st.success("Document enhanced and saved successfully!")
                            else:
                                st.success("Document enhanced but failed to save to database")
                        else:
                            st.warning("""
                            Document wasn't enhanced. Possible reasons:
                            - The content was too short
                            - The server is under heavy load
                            - The model didn't make significant changes
                            """)
                    except Exception as e:
                        st.error(f"Enhancement failed: {str(e)}")
            
            if 'enhanced_text' in st.session_state:
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("Original Version")
                    st.text_area(
                        "Original View",
                        value=original_text,
                        height=400,
                        key=f"orig_view_{file_key}"
                    )
                with col2:
                    st.subheader("Enhanced Version")
                    st.text_area(
                        "Enhanced View",
                        value=st.session_state.enhanced_text,
                        height=400,
                        key=f"enh_view_{file_key}"
                    )
                
                st.download_button(
                    "💾 Download Enhanced Doc",
                    data=create_word_doc(st.session_state.enhanced_text),
                    file_name=f"enhanced_{uploaded_file.name}",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"dl_{file_key}"
                )
        
        except Exception as e:
            st.error(f"Error processing document: {str(e)}")

if __name__ == "__main__":
    main()