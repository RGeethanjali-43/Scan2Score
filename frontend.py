import streamlit as st
import requests
from PIL import Image
import io
import base64
import fitz  # PyMuPDF

# API Configuration
API_BASE_URL = "http://localhost:8000"

# Page config
st.set_page_config(
    page_title="Scan2Score - PDF Answer Evaluator",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ===================== CUSTOM CSS =====================
st.markdown("""
<style>
    .main-title {
        font-size: 3.5rem;
        font-weight: bold;
        text-align: center;
        margin-bottom: 0.5rem;
        color: #ffffff;
    }
    .subtitle {
        text-align: center;
        color: #888;
        margin-bottom: 2rem;
    }
    .continuation-badge {
        background-color: #1E90FF;
        color: white;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: bold;
    }

    /* ================= RED CLEAR BUTTON ================= */
    button[kind="secondary"][data-testid="baseButton-secondary"] {
        background-color: #dc3545 !important;
        color: white !important;
        border: none !important;
        font-weight: 600;
    }
    button[kind="secondary"][data-testid="baseButton-secondary"]:hover {
        background-color: #b52a37 !important;
        color: white !important;
    }

    /* ================= RED BROWSE FILES BUTTON ================= */
    section[data-testid="stFileUploader"] button {
        background-color: #dc3545 !important;
        color: white !important;
        border: none !important;
        font-weight: 600;
    }
    section[data-testid="stFileUploader"] button:hover {
        background-color: #b52a37 !important;
        color: white !important;
    }

    /* Keep buttons full width */
    div[data-testid="stButton"] button {
        width: 100%;
    }

    div[data-testid="metric-container"] {
        background-color: #1e1e1e;
        padding: 0.5rem;
        border-radius: 5px;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'question_pdf_id' not in st.session_state:
    st.session_state.question_pdf_id = None
if 'answer_pdf_id' not in st.session_state:
    st.session_state.answer_pdf_id = None
if 'question_filename' not in st.session_state:
    st.session_state.question_filename = None
if 'answer_filename' not in st.session_state:
    st.session_state.answer_filename = None
if 'question_selections' not in st.session_state:
    st.session_state.question_selections = []
if 'answer_selections' not in st.session_state:
    st.session_state.answer_selections = []
if 'evaluation_results' not in st.session_state:
    st.session_state.evaluation_results = []
if 'zoom' not in st.session_state:
    st.session_state.zoom = 0.7
if 'max_marks' not in st.session_state:
    st.session_state.max_marks = 10
if 'question_page' not in st.session_state:
    st.session_state.question_page = 0
if 'answer_page' not in st.session_state:
    st.session_state.answer_page = 0
if 'continuation_mode_q' not in st.session_state:
    st.session_state.continuation_mode_q = False
if 'continuation_mode_a' not in st.session_state:
    st.session_state.continuation_mode_a = False
if 'question_parts' not in st.session_state:
    st.session_state.question_parts = {}  # {index: [parts]}
if 'answer_parts' not in st.session_state:
    st.session_state.answer_parts = {}  # {index: [parts]}
if 'upload_counter' not in st.session_state:
    st.session_state.upload_counter = 0  # Counter to reset file uploaders

# Helper Functions
def upload_pdf_to_api(uploaded_file, pdf_type):
    """Upload PDF to FastAPI backend"""
    try:
        files = {'file': (uploaded_file.name, uploaded_file.getvalue(), 'application/pdf')}
        response = requests.post(f"{API_BASE_URL}/upload", files=files)
        if response.status_code == 200:
            result = response.json()
            if pdf_type == "question":
                st.session_state.question_pdf_id = result['pdf_id']
                st.session_state.question_filename = result['filename']
            else:
                st.session_state.answer_pdf_id = result['pdf_id']
                st.session_state.answer_filename = result['filename']
            return result
        else:
            st.error(f"Upload failed: {response.text}")
            return None
    except Exception as e:
        st.error(f"Error uploading PDF: {str(e)}")
        return None

def open_tkinter_selector(pdf_id, page=0, zoom=0.7, continuation=False):
    """Call the backend to open Tkinter selector"""
    try:
        response = requests.get(
            f"{API_BASE_URL}/preview/{pdf_id}",
            params={"page": page, "zoom": zoom, "continuation": continuation}
        )
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"Failed to open selector: {response.text}")
            return None
    except Exception as e:
        st.error(f"Error opening selector: {str(e)}")
        return None

def extract_text_from_coords(pdf_id, page_num, coords, zoom):
    """Extract text from coordinates"""
    try:
        payload = {
            "pdf_id": pdf_id,
            "page_number": page_num,
            "coordinates": coords,
            "zoom": zoom
        }
        response = requests.post(f"{API_BASE_URL}/extract-text", json=payload)
        if response.status_code == 200:
            return response.json()['extracted_text']
        else:
            st.error(f"Text extraction failed: {response.text}")
            return None
    except Exception as e:
        st.error(f"Error extracting text: {str(e)}")
        return None

def store_continuation(pdf_id, question_index, text_type, text):
    """Store continuation text"""
    try:
        response = requests.post(
            f"{API_BASE_URL}/store-continuation",
            params={
                "pdf_id": pdf_id,
                "question_index": question_index,
                "text_type": text_type,
                "text": text
            }
        )
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        st.error(f"Error storing continuation: {str(e)}")
        return None

def evaluate_full(pdf_id, question_page, answer_page, question_coords, answer_coords, max_marks, zoom, question_index):
    """Call full evaluation endpoint"""
    try:
        payload = {
            "pdf_id": pdf_id,
            "question_page": question_page,
            "answer_page": answer_page,
            "question_coords": question_coords,
            "answer_coords": answer_coords,
            "max_marks": max_marks,
            "zoom": zoom,
            "question_index": question_index
        }
        response = requests.post(f"{API_BASE_URL}/evaluate-full", json=payload)
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"Evaluation failed: {response.text}")
            return None
    except Exception as e:
        st.error(f"Error during evaluation: {str(e)}")
        return None

def get_total_marks():
    """Get total marks from backend"""
    try:
        response = requests.get(f"{API_BASE_URL}/total-marks")
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"Failed to get total marks: {response.text}")
            return None
    except Exception as e:
        st.error(f"Error getting total marks: {str(e)}")
        return None

def clear_marks():
    """Clear marks storage in backend"""
    try:
        response = requests.post(f"{API_BASE_URL}/clear-marks")
        return response.status_code == 200
    except Exception as e:
        st.error(f"Error clearing marks: {str(e)}")
        return False

def clear_continuation():
    """Clear continuation storage in backend"""
    try:
        response = requests.post(f"{API_BASE_URL}/clear-continuation")
        return response.status_code == 200
    except Exception as e:
        st.error(f"Error clearing continuation: {str(e)}")
        return False

def delete_pdf(pdf_id):
    """Delete PDF from backend"""
    try:
        response = requests.delete(f"{API_BASE_URL}/pdf/{pdf_id}")
        return response.status_code == 200
    except Exception as e:
        st.error(f"Error deleting PDF: {str(e)}")
        return False

def clear_all():
    """Clear all session state and backend storage"""
    if st.session_state.question_pdf_id:
        delete_pdf(st.session_state.question_pdf_id)
    if st.session_state.answer_pdf_id:
        delete_pdf(st.session_state.answer_pdf_id)
    
    clear_marks()
    clear_continuation()
    
    st.session_state.question_pdf_id = None
    st.session_state.answer_pdf_id = None
    st.session_state.question_filename = None
    st.session_state.answer_filename = None
    st.session_state.question_selections = []
    st.session_state.answer_selections = []
    st.session_state.evaluation_results = []
    st.session_state.continuation_mode_q = False
    st.session_state.continuation_mode_a = False
    st.session_state.question_parts = {}
    st.session_state.answer_parts = {}
    st.session_state.upload_counter += 1  # Increment to reset file uploaders

# Sidebar
with st.sidebar:
    with st.expander("📖 Instructions", expanded=False):
        st.markdown("""
        <div style="background-color: #2d2d2d; padding: 1.5rem; border-radius: 8px;">
        <ol>
            <li>Upload <b>Question Paper</b> and <b>Answer Sheet</b></li>
            <li>Set page numbers for each PDF</li>
            <li>Select regions (use <b>Continue</b> for multi-part content)</li>
            <li>Click <b>Evaluate</b> to analyze</li>
            <li>Click <b>Total Marks</b> for final score</li>
        </ol>
        <hr>
        <p><b>Continue Feature:</b> If your answer spans multiple regions, select the first part, click 'Continue' in the selector, then select additional parts. All parts will be combined.</p>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    st.markdown("### ⚙️ Settings")
    
    st.markdown("**Question Paper Page**")
    question_page = st.number_input(
        "Question Page number",
        min_value=0,
        value=st.session_state.question_page,
        step=1,
        help="Page number for Question PDF",
        key="q_page_input"
    )
    st.session_state.question_page = question_page
    
    st.markdown("**Answer Sheet Page**")
    answer_page = st.number_input(
        "Answer Page number",
        min_value=0,
        value=st.session_state.answer_page,
        step=1,
        help="Page number for Answer PDF",
        key="a_page_input"
    )
    st.session_state.answer_page = answer_page
    
    st.markdown("---")
    
    zoom_options = {
        "50%": 0.5,
        "70%": 0.7,
        "100%": 1.0,
        "150%": 1.5,
        "200%": 2.0
    }
    zoom_label = st.selectbox(
        "Zoom Level",
        options=list(zoom_options.keys()),
        index=1
    )
    st.session_state.zoom = zoom_options[zoom_label]
    
    st.session_state.max_marks = st.number_input(
        "Maximum Marks",
        min_value=1,
        max_value=100,
        value=10,
        step=1
    )
    
    st.markdown("---")
    
    col_clear, col_about = st.columns(2)
    
    with col_clear:
        if st.button("🗑️Clear", key="clear_btn", type="secondary"):
            clear_all()
            st.rerun()
    
    with col_about:
        with st.expander("ℹ️ About"):
            st.markdown("""
            **Scan2Score v1.1**
            
            AI-powered evaluator with continuation support
            
            Built with Streamlit + FastAPI
            """)

# Main Content
st.markdown('<h1 class="main-title">📝 Scan2Score</h1>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">Upload answer script and question script to check level of performance</p>', unsafe_allow_html=True)

# Two column layout for uploads
col1, col2 = st.columns(2)

with col1:
    st.markdown("### 📄 Question Paper")
    
    question_file = st.file_uploader(
        "Drag and drop file here",
        type=['pdf'],
        key=f'question_uploader_{st.session_state.upload_counter}',
        help="Limit 200MB per file • PDF"
    )
    
    if question_file is not None and st.session_state.question_pdf_id is None:
        with st.spinner("Uploading Question Paper..."):
            result = upload_pdf_to_api(question_file, "question")
            if result:
                st.success(f"✅ {result['filename']} ({result['page_count']} pages)")
    
    # Show continuation indicator
    if st.session_state.continuation_mode_q:
        st.info("🔄 CONTINUATION MODE: Select additional question regions")
        
    if st.button("🖱️ Select Question Regions", key="select_q", use_container_width=True):
        if st.session_state.question_pdf_id:
            with st.spinner(f"Opening Question Paper (Page {st.session_state.question_page})..."):
                result = open_tkinter_selector(
                    st.session_state.question_pdf_id,
                    st.session_state.question_page,
                    st.session_state.zoom,
                    st.session_state.continuation_mode_q
                )
                if result and result['selections']:
                    if st.session_state.continuation_mode_q:
                        # Append to existing selections
                        current_idx = len(st.session_state.question_selections) - 1
                        for sel in result['selections']:
                            # Extract and store text
                            text = extract_text_from_coords(
                                st.session_state.question_pdf_id,
                                st.session_state.question_page,
                                sel,
                                st.session_state.zoom
                            )
                            if text:
                                store_continuation(
                                    st.session_state.answer_pdf_id,
                                    current_idx,
                                    "question",
                                    text
                                )
                                if current_idx not in st.session_state.question_parts:
                                    st.session_state.question_parts[current_idx] = []
                                st.session_state.question_parts[current_idx].append(text)
                        
                        if result.get('continue_requested'):
                            st.info(f"✅ Added {len(result['selections'])} more part(s). Continue again or proceed.")
                        else:
                            st.session_state.continuation_mode_q = False
                            st.success(f"✅ Continuation complete! Total parts: {len(st.session_state.question_parts.get(current_idx, []))}")
                    else:
                        st.session_state.question_selections = result['selections']
                        if result.get('continue_requested'):
                            st.session_state.continuation_mode_q = True
                            # Store first part
                            current_idx = len(st.session_state.question_selections) - 1
                            for sel in result['selections']:
                                text = extract_text_from_coords(
                                    st.session_state.question_pdf_id,
                                    st.session_state.question_page,
                                    sel,
                                    st.session_state.zoom
                                )
                                if text:
                                    store_continuation(
                                        st.session_state.answer_pdf_id,
                                        current_idx,
                                        "question",
                                        text
                                    )
                                    if current_idx not in st.session_state.question_parts:
                                        st.session_state.question_parts[current_idx] = []
                                    st.session_state.question_parts[current_idx].append(text)
                            st.info("🔄 Continue mode activated. Select more regions.")
                        else:
                            st.success(f"✅ {len(result['selections'])} question(s) selected")
                    st.rerun()
        else:
            st.warning("Please upload question paper first!")

with col2:
    st.markdown("### 📝 Answer Sheet")
    
    answer_file = st.file_uploader(
        "Drag and drop file here",
        type=['pdf'],
        key=f'answer_uploader_{st.session_state.upload_counter}',
        help="Limit 200MB per file • PDF"
    )
    
    if answer_file is not None and st.session_state.answer_pdf_id is None:
        with st.spinner("Uploading Answer Sheet..."):
            result = upload_pdf_to_api(answer_file, "answer")
            if result:
                st.success(f"✅ {result['filename']} ({result['page_count']} pages)")
    
    # Show continuation indicator
    if st.session_state.continuation_mode_a:
        st.info("🔄 CONTINUATION MODE: Select additional answer regions")
        
    if st.button("🖱️ Select Answer Regions", key="select_a", use_container_width=True):
        if st.session_state.answer_pdf_id:
            with st.spinner(f"Opening Answer Sheet (Page {st.session_state.answer_page})..."):
                result = open_tkinter_selector(
                    st.session_state.answer_pdf_id,
                    st.session_state.answer_page,
                    st.session_state.zoom,
                    st.session_state.continuation_mode_a
                )
                if result and result['selections']:
                    if st.session_state.continuation_mode_a:
                        # Append to existing selections
                        current_idx = len(st.session_state.answer_selections) - 1
                        for sel in result['selections']:
                            text = extract_text_from_coords(
                                st.session_state.answer_pdf_id,
                                st.session_state.answer_page,
                                sel,
                                st.session_state.zoom
                            )
                            if text:
                                store_continuation(
                                    st.session_state.answer_pdf_id,
                                    current_idx,
                                    "answer",
                                    text
                                )
                                if current_idx not in st.session_state.answer_parts:
                                    st.session_state.answer_parts[current_idx] = []
                                st.session_state.answer_parts[current_idx].append(text)
                        
                        if result.get('continue_requested'):
                            st.info(f"✅ Added {len(result['selections'])} more part(s). Continue again or proceed.")
                        else:
                            st.session_state.continuation_mode_a = False
                            st.success(f"✅ Continuation complete! Total parts: {len(st.session_state.answer_parts.get(current_idx, []))}")
                    else:
                        st.session_state.answer_selections = result['selections']
                        if result.get('continue_requested'):
                            st.session_state.continuation_mode_a = True
                            # Store first part
                            current_idx = len(st.session_state.answer_selections) - 1
                            for sel in result['selections']:
                                text = extract_text_from_coords(
                                    st.session_state.answer_pdf_id,
                                    st.session_state.answer_page,
                                    sel,
                                    st.session_state.zoom
                                )
                                if text:
                                    store_continuation(
                                        st.session_state.answer_pdf_id,
                                        current_idx,
                                        "answer",
                                        text
                                    )
                                    if current_idx not in st.session_state.answer_parts:
                                        st.session_state.answer_parts[current_idx] = []
                                    st.session_state.answer_parts[current_idx].append(text)
                            st.info("🔄 Continue mode activated. Select more regions.")
                        else:
                            st.success(f"✅ {len(result['selections'])} answer(s) selected")
                    st.rerun()
        else:
            st.warning("Please upload answer sheet first!")

# Compact evaluation section
if st.session_state.question_pdf_id and st.session_state.answer_pdf_id:
    st.markdown("---")
    
    col_m1, col_m2, col_btn1, col_btn2 = st.columns([1, 1, 1, 1])
    
    with col_m1:
        q_count = len(st.session_state.question_selections)
        q_label = f"{q_count}"
        if any(idx in st.session_state.question_parts for idx in range(q_count)):
            q_label += " 🔄"
        st.metric("Questions", q_label)
    
    with col_m2:
        a_count = len(st.session_state.answer_selections)
        a_label = f"{a_count}"
        if any(idx in st.session_state.answer_parts for idx in range(a_count)):
            a_label += " 🔄"
        st.metric("Answers", a_label)
    
    with col_btn1:
        evaluate_btn = st.button(
            "🚀 Evaluate",
            type="primary",
            disabled=(len(st.session_state.question_selections) == 0 or 
                     len(st.session_state.answer_selections) == 0 or
                     st.session_state.continuation_mode_q or
                     st.session_state.continuation_mode_a)
        )
    
    with col_btn2:
        total_marks_btn = st.button(
            "📊 Total Marks",
            type="secondary"
        )
    
    if evaluate_btn:
        num_pairs = min(len(st.session_state.question_selections), 
                       len(st.session_state.answer_selections))
        
        if num_pairs == 0:
            st.error("⚠️ Please select both question and answer regions!")
        else:
            st.session_state.evaluation_results = []
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for i in range(num_pairs):
                status_text.text(f"Evaluating Question {i+1}/{num_pairs}...")
                
                q_coords = st.session_state.question_selections[i]
                a_coords = st.session_state.answer_selections[i]
                
                result = evaluate_full(
                    st.session_state.answer_pdf_id,
                    st.session_state.question_page,
                    st.session_state.answer_page,
                    q_coords,
                    a_coords,
                    st.session_state.max_marks,
                    st.session_state.zoom,
                    i
                )
                
                if result:
                    st.session_state.evaluation_results.append({
                        'question_num': i + 1,
                        'question': result['question'],
                        'answer': result['raw_answer'],
                        'evaluation': result['evaluation'],
                        'has_continuation': i in st.session_state.question_parts or i in st.session_state.answer_parts
                    })
                
                progress_bar.progress((i + 1) / num_pairs)
            
            status_text.text("✅ Evaluation Complete!")
            st.rerun()
    
    if total_marks_btn:
        with st.spinner("Calculating total marks..."):
            total_result = get_total_marks()
            if total_result:
                st.success(f"### 🎯 Final Score: {total_result['total_awarded']}/{total_result['total_possible']} ({total_result['percentage']:.1f}%)")
                st.info(f"Evaluated {total_result['count']} question(s)")
    
    # Display results
    if st.session_state.evaluation_results:
        st.markdown("---")
        st.markdown("### 📊 Evaluation Results")
        
        for result in st.session_state.evaluation_results:
            continuation_badge = " <span class='continuation-badge'>CONTINUED</span>" if result.get('has_continuation') else ""
            with st.expander(f"📝 Question {result['question_num']}{continuation_badge}", expanded=False):
                col_q, col_r = st.columns([2, 1])
                
                with col_q:
                    # st.markdown("**Corrected Question:**")
                    # st.info(result['evaluation'].get('corrected_question', result['question']))
                    
                    st.markdown("**Corrected Answer:**")
                    st.info(result['evaluation']['corrected_answer'])
                    
                    st.markdown("**Justification:**")
                    st.warning(result['evaluation']['justification'])
                
                with col_r:
                    marks = result['evaluation']['marks_awarded']
                    max_m = result['evaluation']['max_marks']
                    percent = (marks / max_m * 100) if max_m > 0 else 0
                    
                    if percent >= 75:
                        color = "green"
                    elif percent >= 50:
                        color = "orange"
                    else:
                        color = "red"
                    
                    st.markdown(f"""
                    <div style="background-color: #{color}22; padding: 2rem; border-radius: 10px; text-align: center; border: 2px solid {color};">
                        <h1 style="color: {color}; margin: 0; font-size: 3rem;">{marks}/{max_m}</h1>
                        <p style="font-size: 1.5rem; color: {color}; margin: 10px 0;">{percent:.1f}%</p>
                    </div>
                    """, unsafe_allow_html=True)

# Footer
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #666; padding: 1rem;">
    
""", unsafe_allow_html=True)