import io
import os
import json
import asyncio
from typing import Optional

import numpy as np
from PIL import Image
import fitz  # PyMuPDF
from dotenv import load_dotenv
from groq import Groq

from fastapi import FastAPI, File, UploadFile, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

# Load env
load_dotenv()
groq_api_key = os.getenv("GROQ_API_KEY") or os.getenv("groq_key")
if not groq_api_key:
    raise RuntimeError("GROQ_API_KEY (or groq_key) not found in environment. Please set it in your .env file.")
groq_client = Groq(api_key=groq_api_key)

app = FastAPI(title="Scan2Score API")

# Allow CORS for local testing (adjust origins in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Copyed over helper functions from your script (slightly adapted) ---

_reader = None
def get_reader(lang_list=None, use_gpu=False):
    global _reader
    if _reader is not None:
        return _reader
    lang_list = lang_list or ['en']
    try:
        import easyocr
    except Exception as e:
        raise RuntimeError(
            "easyocr import failed. Ensure venv is activated and packages installed:\n"
            r"env\Scripts\activate && pip install --upgrade --force-reinstall \"numpy<2\" easyocr PyMuPDF torch\n"
            f"Import error: {e}"
        )
    try:
        _reader = easyocr.Reader(lang_list, gpu=use_gpu)
    except Exception as e:
        raise RuntimeError(
            "Failed to initialize easyocr.Reader. Likely NumPy/PyTorch ABI mismatch.\n"
            "Downgrade NumPy with: pip install --upgrade --force-reinstall \"numpy<2\"\n"
            f"Initialization error: {e}"
        )
    return _reader

def extract_text_from_pdf(pdf_bytes: bytes, use_gpu: bool = False) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    full_text = []

    gpu_available = use_gpu
    try:
        import torch
        gpu_available = use_gpu and torch.cuda.is_available()
    except Exception:
        gpu_available = False

    reader = get_reader(['en'], use_gpu=gpu_available)

    for page_number in range(len(doc)):
        page = doc.load_page(page_number)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img_bytes = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")

        # reduce size and ensure contiguous uint8 numpy array
        img = img.resize((max(1, img.width // 2), max(1, img.height // 2)))
        img_array = np.array(img)
        if img_array.dtype != np.uint8:
            img_array = img_array.astype(np.uint8)
        img_array = np.ascontiguousarray(img_array)

        try:
            result = reader.readtext(img_array, detail=0)
        except Exception as e:
            # try to recover by reinitializing reader on CPU once
            if gpu_available:
                reader = get_reader(['en'], use_gpu=False)
                result = reader.readtext(img_array, detail=0)
            else:
                raise RuntimeError(f"OCR failed on page {page_number}: {e}")

        page_text = "\n".join(result)
        full_text.append(page_text)

    doc.close()
    return "\n".join(full_text)

SIMPLE_CHECK_PROMPT = """
You are an exam paper evaluator.

You will receive:
1) OCR extracted QUESTION PAPER text
2) OCR extracted ANSWER SHEET text

Your task:
- Read all questions.
- Read all student answers.
- Decide if the answers correctly and meaningfully answer each question.
- If answers match the questions → return overall_correct = true
- If any answer is wrong, incomplete, irrelevant, or mismatched → overall_correct = false

Return ONLY a JSON object in this exact format:

{
  "overall_correct": true/false,
  "summary": "one short sentence summary"
}

IMPORTANT: 
- Do NOT use apostrophes or single quotes in your summary text
- Use simple punctuation only
- DO NOT add any extra text outside the JSON object
- Ensure valid JSON format
"""

def _extract_groq_content(resp):
    """
    Try several likely response shapes and return the assistant text.
    """
    # If object-like with attributes
    try:
        return resp.choices[0].message.content
    except Exception:
        pass

    try:
        return resp.choices[0].message["content"]
    except Exception:
        pass

    # If dictionary-like
    try:
        d = dict(resp)
    except Exception:
        try:
            d = resp.__dict__
        except Exception:
            d = None

    if isinstance(d, dict):
        try:
            return d["choices"][0]["message"]["content"]
        except Exception:
            pass
        try:
            return d["choices"][0]["text"]
        except Exception:
            pass
        try:
            return d["output"][0]["content"][0]["text"]
        except Exception:
            pass

    raw = str(resp)
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end != -1 and end > start:
        return raw[start:end]
    return raw

def evaluate_answers_simple_sync(question_text: str, answer_text: str) -> dict:
    """
    Synchronous worker that calls Groq and returns parsed JSON.
    """
    messages = [
        {"role": "system", "content": SIMPLE_CHECK_PROMPT},
        {"role": "user", "content":
            "QUESTION PAPER:\n" + question_text +
            "\n\nANSWER SHEET:\n" + answer_text
        }
    ]

    resp = groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=messages,
        temperature=0.0,
        max_tokens=600
    )

    raw = _extract_groq_content(resp)
    
    # Clean the response - remove markdown code blocks if present
    raw = raw.strip()
    if raw.startswith("```json"):
        raw = raw[7:]
    if raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()
    
    try:
        # Try direct parsing first
        result = json.loads(raw)
        # Ensure we return only summary
        return {"summary": result.get("summary", "Evaluation completed")}
    except json.JSONDecodeError as e:
        # Try to extract JSON from the response
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start != -1 and end > start:
                json_blob = raw[start:end]
                result = json.loads(json_blob)
                return {"summary": result.get("summary", "Evaluation completed")}
        except Exception:
            pass
        
        # If all parsing fails, return error detail
        raise RuntimeError(
            f"Failed to parse assistant response as JSON.\n"
            f"Parsing error: {str(e)}\n"
            f"Raw response (first 500 chars): {raw[:500]}"
        )

# --- FastAPI request/response models ---

class TextPayload(BaseModel):
    question_text: str
    answer_text: str

# --- Endpoints ---

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/evaluate-text")
async def evaluate_text(payload: TextPayload):
    """
    Evaluate using already-extracted text.
    """
    try:
        result = await asyncio.to_thread(
            evaluate_answers_simple_sync, 
            payload.question_text, 
            payload.answer_text
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result

@app.post("/evaluate-files")
async def evaluate_files(
    question_pdf: UploadFile = File(...), 
    answer_pdf: UploadFile = File(...)
):
    """
    Upload two PDFs (multipart form-data). Returns the evaluation JSON.
    """
    # Validate content types (basic)
    if question_pdf.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(
            status_code=400, 
            detail="question_pdf must be a PDF file"
        )
    if answer_pdf.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(
            status_code=400, 
            detail="answer_pdf must be a PDF file"
        )

    try:
        q_bytes = await question_pdf.read()
        a_bytes = await answer_pdf.read()
    except Exception as e:
        raise HTTPException(
            status_code=400, 
            detail=f"Failed to read uploaded files: {e}"
        )

    # Perform OCR in thread to avoid blocking event loop
    try:
        q_text = await asyncio.to_thread(extract_text_from_pdf, q_bytes, False)
        a_text = await asyncio.to_thread(extract_text_from_pdf, a_bytes, False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR failed: {e}")

    # Evaluate via Groq (also in thread)
    try:
        result = await asyncio.to_thread(
            evaluate_answers_simple_sync, 
            q_text, 
            a_text
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {e}")

    return result

# If you want to run directly: uvicorn app:app --reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)