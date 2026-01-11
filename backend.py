from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List
import fitz  # PyMuPDF
from PIL import Image, ImageTk
import tkinter as tk
import easyocr
import io
import numpy as np
from dotenv import load_dotenv
from groq import Groq
import os
import json
import uuid
from pathlib import Path
import base64
import threading

# Load environment variables
load_dotenv()

# Initialize FastAPI
app = FastAPI(title="PDF Answer Sheet Evaluator", version="1.0")

# Initialize Groq client
groq_api_key = os.getenv("GROQ_API_KEY") or os.getenv("groq_key")
if not groq_api_key:
    raise RuntimeError("GROQ_API_KEY not found in environment")
groq_client = Groq(api_key=groq_api_key)

# Initialize EasyOCR
reader = easyocr.Reader(['en'])

# Storage for uploaded PDFs
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# In-memory storage (use database in production)
pdf_storage = {}
selection_storage = {}  # Store user selections from Tkinter
marks_storage = []  # Store evaluation marks

# ==================== MODELS ====================
class Coordinates(BaseModel):
    x0: int
    y0: int
    x1: int
    y1: int

class ExtractTextRequest(BaseModel):
    pdf_id: str
    page_number: int = 0
    coordinates: Coordinates
    zoom: float = 0.7

class EvaluateAnswerRequest(BaseModel):
    question: str
    ocr_answer: str
    max_marks: int

class FullEvaluationRequest(BaseModel):
    pdf_id: str
    question_page: int = 0
    answer_page: int = 0
    question_coords: Coordinates
    answer_coords: Coordinates
    max_marks: int
    zoom: float = 0.7

# ==================== TKINTER PREVIEW ====================
class PDFSelector:
    def __init__(self, pdf_path: str, page_num: int = 0, zoom: float = 0.7):
        self.pdf_path = pdf_path
        self.page_num = page_num
        self.zoom = zoom
        self.selections = []
        self.current_rect = None
        self.start_x = 0
        self.start_y = 0
        self.all_selections = []  # Store all selections from all pages with coordinates
        self.accumulated_ocr_texts = []  # Store all OCR texts from all pages
        self.tk_img = None  # Keep reference to prevent garbage collection
        
        # Load PDF
        self.doc = fitz.open(pdf_path)
        self.total_pages = len(self.doc)
        
        # Validate initial page number
        if page_num >= self.total_pages:
            self.doc.close()
            raise ValueError(f"Page {page_num} does not exist. PDF has {self.total_pages} pages (0-{self.total_pages-1})")
        
        # Create Tkinter window
        self.root = tk.Tk()
        self.root.title(f"PDF Selector - Page {self.page_num + 1}/{self.total_pages} (Zoom: {int(zoom*100)}%)")
        
        # ===== TOP SECTION: Buttons FIRST (Always Visible) =====
        button_frame = tk.Frame(self.root, bg="#f0f0f0", pady=10)
        button_frame.pack(side=tk.TOP, fill=tk.X)
        
        # Left side buttons
        left_buttons = tk.Frame(button_frame, bg="#f0f0f0")
        left_buttons.pack(side=tk.LEFT, padx=10)
        
        tk.Button(
            left_buttons,
            text="Clear Last",
            command=self.clear_last,
            bg="#FFA500",
            fg="white",
            width=12,
            height=2,
            font=("Arial", 10, "bold"),
            cursor="hand2"
        ).pack(side=tk.LEFT, padx=5)
        
        tk.Button(
            left_buttons,
            text="Clear All",
            command=self.clear_all,
            bg="#DC143C",
            fg="white",
            width=12,
            height=2,
            font=("Arial", 10, "bold"),
            cursor="hand2"
        ).pack(side=tk.LEFT, padx=5)
        
        # Center - Page navigation
        nav_frame = tk.Frame(button_frame, bg="#f0f0f0")
        nav_frame.pack(side=tk.LEFT, padx=20)
        
        tk.Button(
            nav_frame,
            text="◄ Prev",
            command=self.prev_page,
            bg="#4682B4",
            fg="white",
            width=8,
            height=2,
            font=("Arial", 10, "bold"),
            cursor="hand2"
        ).pack(side=tk.LEFT, padx=3)
        
        self.page_label = tk.Label(
            nav_frame,
            text=f"{self.page_num + 1}/{self.total_pages}",
            bg="#f0f0f0",
            font=("Arial", 12, "bold"),
            width=8
        )
        self.page_label.pack(side=tk.LEFT, padx=5)
        
        tk.Button(
            nav_frame,
            text="Next ►",
            command=self.next_page,
            bg="#4682B4",
            fg="white",
            width=8,
            height=2,
            font=("Arial", 10, "bold"),
            cursor="hand2"
        ).pack(side=tk.LEFT, padx=3)
        
        # Right side buttons
        right_buttons = tk.Frame(button_frame, bg="#f0f0f0")
        right_buttons.pack(side=tk.RIGHT, padx=10)
        
        tk.Button(
            right_buttons,
            text="➜ CONTINUE",
            command=self.continue_to_next,
            bg="#FF8C00",
            fg="white",
            width=12,
            height=2,
            font=("Arial", 10, "bold"),
            cursor="hand2"
        ).pack(side=tk.LEFT, padx=5)
        
        tk.Button(
            right_buttons,
            text="✓ DONE",
            command=self.finish,
            bg="#228B22",
            fg="white",
            width=12,
            height=2,
            font=("Arial", 10, "bold"),
            cursor="hand2"
        ).pack(side=tk.LEFT, padx=5)
        
        # Instructions below buttons
        self.instruction_label = tk.Label(
            self.root,
            text="📌 Draw rectangles → Click 'CONTINUE' to save OCR text & switch page → Click 'DONE' when finished",
            bg="#FFFFE0",
            font=("Arial", 10),
            pady=8
        )
        self.instruction_label.pack(side=tk.TOP, fill=tk.X)
        
        # ===== SCROLLABLE CANVAS SECTION =====
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Add scrollbars
        v_scrollbar = tk.Scrollbar(main_frame, orient=tk.VERTICAL)
        h_scrollbar = tk.Scrollbar(main_frame, orient=tk.HORIZONTAL)
        
        # Create canvas
        self.canvas = tk.Canvas(
            main_frame,
            width=1200,
            height=650,
            yscrollcommand=v_scrollbar.set,
            xscrollcommand=h_scrollbar.set,
            bg="white"
        )
        
        v_scrollbar.config(command=self.canvas.yview)
        h_scrollbar.config(command=self.canvas.xview)
        
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Status bar at bottom - CREATE BEFORE load_page()
        self.status_label = tk.Label(
            self.root,
            text=f"Selections: 0 | OCR Texts Saved: 0",
            bg="#e0e0e0",
            font=("Arial", 9),
            anchor="w",
            padx=10
        )
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Load initial page AFTER status_label is created
        self.load_page(self.page_num)
        
        # Bind mouse events
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)
        
    def load_page(self, page_num):
        """Load a specific page of the PDF"""
        self.page_num = page_num
        page = self.doc[page_num]
        mat = fitz.Matrix(self.zoom, self.zoom)
        pix = page.get_pixmap(matrix=mat)
        self.img = Image.open(io.BytesIO(pix.tobytes()))
        
        # Keep strong reference to PhotoImage to prevent garbage collection
        self.tk_img = ImageTk.PhotoImage(self.img)
        
        # Update canvas
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)
        self.canvas.config(scrollregion=(0, 0, self.img.width, self.img.height))
        
        # Update title and page label
        self.root.title(f"PDF Selector - Page {self.page_num + 1}/{self.total_pages} (Zoom: {int(self.zoom*100)}%)")
        self.page_label.config(text=f"{self.page_num + 1}/{self.total_pages}")
        
        # Clear current selections (not accumulated ones)
        self.selections = []
        self.update_status()
        
    def next_page(self):
        """Go to next page"""
        if self.page_num < self.total_pages - 1:
            self.load_page(self.page_num + 1)
        else:
            print("⚠ Already on last page")
            
    def prev_page(self):
        """Go to previous page"""
        if self.page_num > 0:
            self.load_page(self.page_num - 1)
        else:
            print("⚠ Already on first page")
    
    def extract_ocr_from_selections(self):
        """Extract OCR text from current selections and save with coordinates"""
        ocr_results = []
        for idx, sel in enumerate(self.selections):
            try:
                # Crop region
                crop = self.img.crop((sel["x0"], sel["y0"], sel["x1"], sel["y1"]))
                crop_np = np.array(crop)
                
                # OCR
                result = reader.readtext(crop_np, detail=0, paragraph=True)
                text = " ".join(result).strip()
                
                # Store selection with coordinates and OCR text
                selection_data = {
                    "page": self.page_num,
                    "region": idx + 1,
                    "x0": sel["x0"],
                    "y0": sel["y0"],
                    "x1": sel["x1"],
                    "y1": sel["y1"],
                    "ocr_text": text
                }
                
                ocr_results.append(selection_data)
                
                if text:
                    # Also add to accumulated OCR texts list (text only)
                    self.accumulated_ocr_texts.append({
                        "page": self.page_num,
                        "region": idx + 1,
                        "text": text
                    })
                    print(f"✓ OCR [{self.page_num + 1}-{idx + 1}]: {text[:50]}...")
                else:
                    print(f"⚠ OCR [{self.page_num + 1}-{idx + 1}]: No text detected")
            except Exception as e:
                print(f"✗ OCR failed for selection {idx + 1}: {str(e)}")
        
        return ocr_results
    
    def continue_to_next(self):
        """Save current selections as OCR text and continue"""
        if not self.selections:
            print("⚠ No selections to save. Draw rectangles first!")
            return
        
        # Extract OCR from current selections
        ocr_results = self.extract_ocr_from_selections()
        
        # Append to all selections
        self.all_selections.extend(ocr_results)
        
        print(f"✓ Saved {len(ocr_results)} selection(s) from page {self.page_num + 1}")
        print(f"✓ Total selections accumulated: {len(self.all_selections)}")
        
        # Clear current page selections
        for sel in self.selections:
            self.canvas.delete(sel["rect_id"])
        self.selections = []
        
        # Update status
        self.update_status()
        
        # Auto-advance to next page if available
        if self.page_num < self.total_pages - 1:
            self.next_page()
            print(f"→ Moved to page {self.page_num + 1}")
        else:
            print("✓ On last page. Click 'DONE' to finish.")
    
    def update_status(self):
        """Update status bar"""
        self.status_label.config(
            text=f"Selections: {len(self.selections)} | Total Saved: {len(self.all_selections)}"
        )
        
    def on_mouse_down(self, event):
        self.start_x = self.canvas.canvasx(event.x)
        self.start_y = self.canvas.canvasy(event.y)
        self.current_rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="red", width=3
        )
    
    def on_mouse_drag(self, event):
        cur_x = self.canvas.canvasx(event.x)
        cur_y = self.canvas.canvasy(event.y)
        self.canvas.coords(
            self.current_rect,
            self.start_x, self.start_y, cur_x, cur_y
        )
    
    def on_mouse_up(self, event):
        cur_x = self.canvas.canvasx(event.x)
        cur_y = self.canvas.canvasy(event.y)
        
        x0 = min(self.start_x, cur_x)
        y0 = min(self.start_y, cur_y)
        x1 = max(self.start_x, cur_x)
        y1 = max(self.start_y, cur_y)
        
        if x1 - x0 > 5 and y1 - y0 > 5:  # Minimum size check
            self.selections.append({
                "x0": int(x0), "y0": int(y0), "x1": int(x1), "y1": int(y1),
                "rect_id": self.current_rect
            })
            self.update_status()
            print(f"✓ Selection {len(self.selections)}: ({int(x0)}, {int(y0)}) to ({int(x1)}, {int(y1)})")
        else:
            self.canvas.delete(self.current_rect)
    
    def clear_last(self):
        if self.selections:
            last = self.selections.pop()
            self.canvas.delete(last["rect_id"])
            self.update_status()
            print("✗ Last selection cleared")
        else:
            print("⚠ No selections to clear")
    
    def clear_all(self):
        for sel in self.selections:
            self.canvas.delete(sel["rect_id"])
        self.selections = []
        self.update_status()
        print("✗ All selections cleared")
    
    def finish(self):
        """Finish and extract remaining selections"""
        # If there are unsaved selections, process them
        if self.selections:
            ocr_results = self.extract_ocr_from_selections()
            self.all_selections.extend(ocr_results)
            print(f"✓ Saved {len(ocr_results)} remaining selection(s) from page {self.page_num + 1}")
        
        print(f"✓ Finished! Total selections: {len(self.all_selections)}")
        self.doc.close()
        self.root.quit()
        self.root.destroy()
    
    def run(self):
        self.root.mainloop()
        return {
            "selections": self.all_selections,
            "ocr_texts": self.accumulated_ocr_texts
        }

def open_pdf_selector(pdf_path: str, page_num: int = 0, zoom: float = 0.7):
    """Open Tkinter window for PDF selection"""
    try:
        selector = PDFSelector(pdf_path, page_num, zoom)
        result = selector.run()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error opening PDF selector: {str(e)}")

# ==================== HELPER FUNCTIONS ====================
def extract_text_from_region(pdf_path: str, page_num: int, coords: Coordinates, zoom: float = 0.7) -> str:
    """Extract text from a specific region of a PDF page"""
    try:
        doc = fitz.open(pdf_path)
        if page_num >= len(doc):
            doc.close()
            raise HTTPException(status_code=400, detail=f"Page {page_num} does not exist. PDF has {len(doc)} pages (0-{len(doc)-1})")
        
        page = doc[page_num]
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        img = Image.open(io.BytesIO(pix.tobytes()))
        
        # Crop to specified region
        crop = img.crop((coords.x0, coords.y0, coords.x1, coords.y1))
        crop_np = np.array(crop)
        
        # OCR
        result = reader.readtext(crop_np, detail=0, paragraph=True)
        text = " ".join(result)
        
        doc.close()
        return text
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR extraction failed: {str(e)}")

def evaluate_answer(question: str, ocr_answer: str, max_marks: int) -> dict:
    """Evaluate student answer using Groq AI with question correction"""
    prompt = f"""
You are an exam evaluator.

TASKS:
1. First, correct spelling mistakes in the QUESTION. Do not change meaning, only fix spelling.
2. Then, correct spelling mistakes in the STUDENT'S ANSWER. Do not change meaning, only fix spelling.
3. Evaluate the corrected answer against the corrected question.
4. Allocate marks out of {max_marks}.
5. Give a short justification (1–2 lines).

RULES:
- Do NOT add new content.
- Do NOT assume missing points.
- Marks must be between 0 and {max_marks}.
- Be strict but fair (university exam style).

ORIGINAL QUESTION:
{question}

STUDENT ANSWER (OCR OUTPUT):
{ocr_answer}

Return the result strictly in JSON format:
{{
  "corrected_question": "...",
  "corrected_answer": "...",
  "marks_awarded": number,
  "max_marks": {max_marks},
  "justification": "..."
}}
"""
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "You evaluate exam answers."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {str(e)}")

# ==================== ENDPOINTS ====================
@app.get("/")
async def root():
    return {
        "message": "PDF Answer Sheet Evaluator API",
        "version": "1.0",
        "endpoints": {
            "/upload": "POST - Upload PDF file",
            "/pdfs": "GET - List uploaded PDFs",
            "/preview/{pdf_id}": "GET - Open Tkinter preview window (returns selections with OCR)",
            "/get-selections/{pdf_id}": "GET - Get saved selections with OCR",
            "/extract-text": "POST - Extract text from region",
            "/evaluate-full": "POST - Full evaluation (question + answer)",
            "/total-marks": "GET - Get total marks",
            "/clear-marks": "POST - Clear marks storage"
        }
    }

@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    """Upload a PDF file"""
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    
    pdf_id = str(uuid.uuid4())
    file_path = UPLOAD_DIR / f"{pdf_id}.pdf"
    
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    
    doc = fitz.open(file_path)
    page_count = len(doc)
    doc.close()
    
    pdf_storage[pdf_id] = {
        "filename": file.filename,
        "path": str(file_path),
        "page_count": page_count
    }
    
    return {
        "pdf_id": pdf_id,
        "filename": file.filename,
        "page_count": page_count,
        "message": "PDF uploaded successfully"
    }

@app.get("/pdfs")
async def list_pdfs():
    """List all uploaded PDFs"""
    return {
        "pdfs": [
            {
                "pdf_id": pdf_id,
                "filename": info["filename"],
                "page_count": info["page_count"]
            }
            for pdf_id, info in pdf_storage.items()
        ]
    }

@app.get("/preview/{pdf_id}")
async def get_preview(pdf_id: str, page: int = 0, zoom: float = 0.7):
    """Open Tkinter window for PDF selection and OCR extraction"""
    if pdf_id not in pdf_storage:
        raise HTTPException(status_code=404, detail="PDF not found")
    
    pdf_path = pdf_storage[pdf_id]["path"]
    
    # Run in main thread (Tkinter requires main thread)
    result = open_pdf_selector(pdf_path, page, zoom)
    selection_storage[pdf_id] = result
    
    return {
        "pdf_id": pdf_id,
        "selections": result["selections"],
        "ocr_texts": result["ocr_texts"],
        "total_selections": len(result["selections"]),
        "message": f"Extracted {len(result['selections'])} selection(s) with OCR"
    }

@app.get("/get-selections/{pdf_id}")
async def get_selections(pdf_id: str):
    """Get previously saved selections with OCR"""
    if pdf_id not in selection_storage:
        return {
            "pdf_id": pdf_id,
            "selections": [],
            "ocr_texts": [],
            "message": "No selections found"
        }
    
    result = selection_storage[pdf_id]
    return {
        "pdf_id": pdf_id,
        "selections": result.get("selections", []),
        "ocr_texts": result.get("ocr_texts", []),
        "total_selections": len(result.get("selections", []))
    }

@app.post("/extract-text")
async def extract_text(request: ExtractTextRequest):
    """Extract text from a specific region of the PDF"""
    if request.pdf_id not in pdf_storage:
        raise HTTPException(status_code=404, detail="PDF not found")
    
    pdf_path = pdf_storage[request.pdf_id]["path"]
    text = extract_text_from_region(
        pdf_path,
        request.page_number,
        request.coordinates,
        request.zoom
    )
    
    return {
        "pdf_id": request.pdf_id,
        "page": request.page_number,
        "extracted_text": text,
        "coordinates": request.coordinates.dict()
    }

@app.post("/evaluate-full")
async def evaluate_full(request: FullEvaluationRequest):
    """Complete evaluation workflow: extract question + answer, then evaluate"""
    if request.pdf_id not in pdf_storage:
        raise HTTPException(status_code=404, detail="PDF not found")
    
    pdf_path = pdf_storage[request.pdf_id]["path"]
    
    # Extract question
    question_text = extract_text_from_region(
        pdf_path,
        request.question_page,
        request.question_coords,
        request.zoom
    )
    
    # Extract answer
    answer_text = extract_text_from_region(
        pdf_path,
        request.answer_page,
        request.answer_coords,
        request.zoom
    )
    
    # Evaluate
    evaluation = evaluate_answer(question_text, answer_text, request.max_marks)
    
    # Store marks
    marks_storage.append({
        "marks_awarded": evaluation["marks_awarded"],
        "max_marks": evaluation["max_marks"]
    })
    
    return {
        "question": question_text,
        "raw_answer": answer_text,
        "evaluation": evaluation
    }

@app.get("/total-marks")
async def get_total_marks():
    """Calculate and return total marks"""
    if not marks_storage:
        return {
            "total_awarded": 0,
            "total_possible": 0,
            "percentage": 0,
            "count": 0
        }
    
    total_awarded = sum(item["marks_awarded"] for item in marks_storage)
    total_possible = sum(item["max_marks"] for item in marks_storage)
    percentage = (total_awarded / total_possible * 100) if total_possible > 0 else 0
    
    return {
        "total_awarded": total_awarded,
        "total_possible": total_possible,
        "percentage": round(percentage, 2),
        "count": len(marks_storage)
    }

@app.post("/clear-marks")
async def clear_marks():
    """Clear all stored marks"""
    global marks_storage
    marks_storage = []
    return {"message": "Marks storage cleared"}

@app.delete("/pdf/{pdf_id}")
async def delete_pdf(pdf_id: str):
    """Delete an uploaded PDF"""
    if pdf_id not in pdf_storage:
        raise HTTPException(status_code=404, detail="PDF not found")
    
    file_path = Path(pdf_storage[pdf_id]["path"])
    if file_path.exists():
        file_path.unlink()
    
    del pdf_storage[pdf_id]
    
    if pdf_id in selection_storage:
        del selection_storage[pdf_id]
    
    return {"message": "PDF deleted successfully"}

# ==================== RUN SERVER ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)