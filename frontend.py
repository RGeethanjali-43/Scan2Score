import streamlit as st
import requests
import json

# Page configuration
st.set_page_config(
    page_title="Scan2Score",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for styling
st.markdown("""
    <style>
    .main-title {
        text-align: center;
        color: #1E88E5;
        font-size: 3.5rem;
        font-weight: 700;
        margin-bottom: 0.5rem;
        text-shadow: 2px 2px 4px rgba(0,0,0,0.1);
    }
    .subtitle {
        text-align: center;
        color: #546E7A;
        font-size: 1.2rem;
        margin-bottom: 2rem;
        font-weight: 400;
    }
    .upload-section {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 15px;
        box-shadow: 0 8px 20px rgba(0,0,0,0.15);
        margin-bottom: 2rem;
    }
    .upload-label {
        color: white;
        font-size: 1.1rem;
        font-weight: 600;
        margin-bottom: 0.5rem;
    }
    .result-box {
        padding: 2rem;
        border-radius: 15px;
        margin-top: 2rem;
        box-shadow: 0 8px 20px rgba(0,0,0,0.15);
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        text-align: center;
    }
    .result-text {
        font-size: 1.3rem;
        font-weight: 500;
        line-height: 1.6;
        margin: 0;
    }
    .info-box {
        background-color: #E3F2FD;
        border-left: 5px solid #2196F3;
        padding: 1rem;
        border-radius: 8px;
        margin-top: 1rem;
    }
    .stButton>button {
        width: 100%;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        color: white;
        font-size: 1.1rem;
        font-weight: 600;
        padding: 0.75rem;
        border-radius: 10px;
        border: none;
        box-shadow: 0 4px 10px rgba(0,0,0,0.2);
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 15px rgba(0,0,0,0.3);
    }
    </style>
""", unsafe_allow_html=True)

# Initialize session state
if 'question_file' not in st.session_state:
    st.session_state.question_file = None
if 'answer_file' not in st.session_state:
    st.session_state.answer_file = None
if 'evaluation_result' not in st.session_state:
    st.session_state.evaluation_result = None

# API endpoint (hardcoded, not shown to user)
api_url = "http://localhost:8000"

# Sidebar
with st.sidebar:
    # Instructions
    st.markdown("### 📖 Instructions")
    st.markdown("""
    1. Upload the **Question Paper** PDF
    2. Upload the **Answer Sheet** PDF
    3. Click **Evaluate** to analyze
    4. View the summary result
    """)
    
    st.markdown("---")
    
    # Clear button
    if st.button("🗑️ Clear All", key="clear_btn", use_container_width=True):
        st.session_state.question_file = None
        st.session_state.answer_file = None
        st.session_state.evaluation_result = None
        st.rerun()
    
    st.markdown("---")
    
    # About section
    with st.expander("ℹ️ About"):
        st.markdown("""
        **Scan2Score** uses AI to evaluate answer sheets against question papers.
        
        - OCR text extraction
        - AI-powered evaluation
        - Instant feedback
        """)

# Main content
st.markdown('<h1 class="main-title">📝 Scan2Score</h1>', unsafe_allow_html=True)
st.markdown(
    '<p class="subtitle">Upload answer script and question script to check level of performance</p>',
    unsafe_allow_html=True
)

# Upload section
col1, col2 = st.columns(2)

with col1:
    st.markdown('<div class="upload-label">📄 Question Paper</div>', unsafe_allow_html=True)
    question_file = st.file_uploader(
        "Upload Question PDF",
        type=['pdf'],
        key='question_uploader',
        label_visibility='collapsed'
    )
    if question_file:
        st.session_state.question_file = question_file
        st.success(f"✓ {question_file.name}")

with col2:
    st.markdown('<div class="upload-label">✍️ Answer Sheet</div>', unsafe_allow_html=True)
    answer_file = st.file_uploader(
        "Upload Answer PDF",
        type=['pdf'],
        key='answer_uploader',
        label_visibility='collapsed'
    )
    if answer_file:
        st.session_state.answer_file = answer_file
        st.success(f"✓ {answer_file.name}")

st.markdown("<br>", unsafe_allow_html=True)

# Evaluate button
if st.session_state.question_file and st.session_state.answer_file:
    if st.button("🚀 Evaluate Performance", use_container_width=True):
        with st.spinner("🔄 Processing files and evaluating..."):
            try:
                # Prepare files for upload
                files = {
                    'question_pdf': (
                        st.session_state.question_file.name,
                        st.session_state.question_file.getvalue(),
                        'application/pdf'
                    ),
                    'answer_pdf': (
                        st.session_state.answer_file.name,
                        st.session_state.answer_file.getvalue(),
                        'application/pdf'
                    )
                }
                
                # Make API request
                response = requests.post(
                    f"{api_url}/evaluate-files",
                    files=files,
                    timeout=120
                )
                
                if response.status_code == 200:
                    st.session_state.evaluation_result = response.json()
                    st.success("✅ Evaluation completed successfully!")
                else:
                    st.error(f"❌ Error: {response.status_code} - {response.text}")
                    
            except requests.exceptions.ConnectionError:
                st.error("❌ Cannot connect to backend API. Please ensure the server is running.")
            except requests.exceptions.Timeout:
                st.error("❌ Request timed out. The files may be too large or the server is busy.")
            except Exception as e:
                st.error(f"❌ An error occurred: {str(e)}")
else:
    st.info("📌 Please upload both Question Paper and Answer Sheet to continue")

# Display results - ONLY SUMMARY
if st.session_state.evaluation_result:
    result = st.session_state.evaluation_result
    
    st.markdown("## 📊 Evaluation Results")
    
    # Display only the summary in a beautiful box
    summary_text = result.get('summary', 'Evaluation completed')
    
    st.markdown(
        f'<div class="result-box">'
        f'<p class="result-text">📝 {summary_text}</p>'
        f'</div>',
        unsafe_allow_html=True
    )

# Footer
st.markdown("---")
st.markdown(
    "<p style='text-align: center; color: #9E9E9E;'>Powered by AI | Scan2Score v1.0</p>",
    unsafe_allow_html=True
)