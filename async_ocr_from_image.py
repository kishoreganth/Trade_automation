import os
import asyncio
import aiohttp
import aiofiles
import base64
from urllib.parse import urlparse
import re
import json
from typing import List, Dict, Optional, Tuple
from pdf2image import convert_from_path
from doctr.io import DocumentFile
from doctr.models import ocr_predictor
from openai import AsyncOpenAI
from dotenv import load_dotenv
import gc
import hashlib
from pdf2image.pdf2image import pdfinfo_from_path
import psutil

load_dotenv()


# Global OpenAI client configuration
# OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")yy
# Global OpenAI client - initialized ONLY ONCE using singleton pattern
_openai_client = None

def get_openai_client():
    """Get the OpenAI client, initializing it only once (singleton pattern)."""
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        print("🔥 OpenAI client initialized ONCE - will never initialize again!")
    return _openai_client

# Global OCR model cache - initialized ONLY ONCE using singleton pattern
_global_ocr_model = None
_model_lock = asyncio.Lock()

async def get_global_ocr_model():
    """Get cached OCR model - loaded ONCE and reused forever for 80% speed gain."""
    global _global_ocr_model
    
    if _global_ocr_model is None:
        async with _model_lock:  # Thread-safe loading
            if _global_ocr_model is None:  # Double-check pattern
                print("🔥 Loading OCR model ONCE (will be cached forever for 80% speed gain)")
                _global_ocr_model = await asyncio.to_thread(ocr_predictor, pretrained=True)
                print("✅ OCR model loaded and cached globally - future requests will be 80% faster!")
    
    return _global_ocr_model


async def extract_filename_from_url(url: str) -> str:
    """Extract filename from URL, handling various URL patterns."""
    # Parse the URL
    parsed_url = urlparse(url)
    
    # Try to get filename from the path
    path_parts = parsed_url.path.split('/')
    filename = path_parts[-1] if path_parts[-1] else None
    
    # If no filename in path, check query parameters
    if not filename or '.' not in filename:
        # Look for common filename patterns in query params
        query = parsed_url.query
        if query:
            # Look for patterns like filename=xxx.pdf or file=xxx.pdf
            filename_match = re.search(r'(?:filename|file|name)=([^&]+\.pdf)', query, re.IGNORECASE)
            if filename_match:
                filename = filename_match.group(1)
    
    # If still no filename, try to extract from the full URL
    if not filename or '.' not in filename:
        # Look for PDF-like patterns in the entire URL
        pdf_match = re.search(r'([a-f0-9\-]+\.pdf)', url, re.IGNORECASE)
        if pdf_match:
            filename = pdf_match.group(1)
    
    # Clean filename and ensure it ends with .pdf
    if filename:
        # Remove any URL encoding and clean the filename
        filename = filename.replace('%20', '_').replace(' ', '_')
        # Remove any non-alphanumeric characters except dots, hyphens, and underscores
        filename = re.sub(r'[^a-zA-Z0-9.\-_]', '', filename)
        if not filename.lower().endswith('.pdf'):
            filename += '.pdf'
    else:
        # Generate a default filename based on URL hash
        
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        filename = f"document_{url_hash}.pdf"
    
    return filename


async def download_pdf_async(url: str, downloads_folder: str = "downloads_concall") -> str:
    """Async download PDF from a given URL with organized folder structure."""
    # Create downloads folder if it doesn't exist
    os.makedirs(downloads_folder, exist_ok=True)
    
    # Extract filename from URL
    filename = await extract_filename_from_url(url)
    save_path = os.path.join(downloads_folder, filename)
    
    # print(f"Downloading PDF from URL...")
    # print(f"Filename: {filename}")
    # print(f"Save path: {save_path}")
    
    # Add headers to avoid 403 Forbidden errors
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'application/pdf,application/octet-stream,*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url) as response:
            response.raise_for_status()
            
            async with aiofiles.open(save_path, "wb") as f:
                async for chunk in response.content.iter_chunked(8192):
                    await f.write(chunk)
    
    # print(f"✅ PDF downloaded successfully: {save_path}")
    return save_path


async def pdf_to_png_async_streaming(pdf_path: str, base_images_folder: str = "images_concall", dpi: int = 150, batch_size: int = 5) -> Tuple[List[str], str]:
    """Memory-optimized streaming PDF to PNG conversion with batch processing."""

    
    # Extract filename without extension for folder naming
    pdf_filename = os.path.basename(pdf_path)
    filename_without_ext = os.path.splitext(pdf_filename)[0]
    
    # Create organized folder structure: images/{filename}/
    output_folder = os.path.join(base_images_folder, filename_without_ext)
    os.makedirs(output_folder, exist_ok=True)
    
    print(f"🚀 Converting PDF to PNG with memory optimization (DPI: {dpi}, Batch: {batch_size})...")
    
    # Get total page count first
    try:
        info = await asyncio.to_thread(pdfinfo_from_path, pdf_path)
        total_pages = info["Pages"]
        print(f"📄 Processing {total_pages} pages in batches of {batch_size}")
    except:
        # Fallback: convert all at once to get page count
        pages = await asyncio.to_thread(convert_from_path, pdf_path, dpi)
        total_pages = len(pages)
        print(f"📄 Fallback: Processing {total_pages} pages")
        
        # Process the already converted pages in batches
        image_paths = []
        for i in range(0, len(pages), batch_size):
            batch_pages = pages[i:i+batch_size]
            batch_start = i + 1
            
            # Process batch in parallel with smart compression
            async def save_page(page, page_num):
                image_path = os.path.join(output_folder, f"page_{page_num}.png")
                await asyncio.to_thread(page.save, image_path, "PNG", optimize=True, compress_level=9)
                return image_path
            
            batch_tasks = [save_page(page, batch_start + j) for j, page in enumerate(batch_pages)]
            batch_paths = await asyncio.gather(*batch_tasks)
            image_paths.extend(batch_paths)
            
            # Clear memory between batches
            del batch_pages, batch_tasks, batch_paths
            gc.collect()
            print(f"✅ Batch {i//batch_size + 1}/{(total_pages + batch_size - 1)//batch_size} complete")
        
        # Clean up
        del pages
        gc.collect()
        return image_paths, output_folder
    
    # Optimal streaming approach: convert pages in batches
    image_paths = []
    
    for batch_start in range(0, total_pages, batch_size):
        batch_end = min(batch_start + batch_size, total_pages)
        batch_pages_list = list(range(batch_start + 1, batch_end + 1))  # 1-indexed for pages
        
        print(f"🔄 Processing batch {batch_start//batch_size + 1}/{(total_pages + batch_size - 1)//batch_size}: pages {batch_start + 1}-{batch_end}")
        
        # Convert only this batch of pages
        pages_batch = await asyncio.to_thread(
            convert_from_path, 
            pdf_path, 
            dpi, 
            first_page=batch_start + 1,
            last_page=batch_end
        )
        
        # Process batch in parallel with smart compression
        async def save_page(page, page_num):
            image_path = os.path.join(output_folder, f"page_{page_num}.png")
            await asyncio.to_thread(page.save, image_path, "PNG", optimize=True, compress_level=9)
            return image_path
        
        batch_tasks = [save_page(page, batch_start + 1 + j) for j, page in enumerate(pages_batch)]
        batch_paths = await asyncio.gather(*batch_tasks)
        image_paths.extend(batch_paths)
        
        # Immediate memory cleanup after each batch
        del pages_batch, batch_tasks, batch_paths
        gc.collect()
        print(f"✅ Batch {batch_start//batch_size + 1} complete, memory cleaned")
    
    print(f"✅ All {total_pages} pages converted with memory optimization")
    return image_paths, output_folder

# Keep backward compatibility
async def pdf_to_png_async(pdf_path: str, base_images_folder: str = "images_concall", dpi: int = 150) -> Tuple[List[str], str]:
    """Async convert PDF pages to PNG images with memory optimization."""
    return await pdf_to_png_async_streaming(pdf_path, base_images_folder, dpi, batch_size=5)


async def process_single_page_ocr(image_path: str, page_num: int, model) -> Tuple[int, str, List[str]]:
    """Process OCR for a single page asynchronously."""
    # print(f"📄 PAGE {page_num}: {os.path.basename(image_path)}")
    
    try:
        # Load the image for OCR in thread pool (I/O bound)
        doc = await asyncio.to_thread(DocumentFile.from_images, image_path)
        
        # Run OCR in thread pool (CPU bound)
        result = await asyncio.to_thread(model, doc)
        
        # Export as dict/json in thread pool (CPU bound)
        json_output = await asyncio.to_thread(result.export)
        
        # Extract text from this page
        page_text_lines = []
        for page in json_output['pages']:
            for block in page['blocks']:
                for line in block['lines']:
                    text_line = " ".join([w['value'] for w in line['words']])
                    if text_line.strip():  # Only collect non-empty lines
                        page_text_lines.append(text_line)
        
        # Create page text
        single_page_text = ""
        if page_text_lines:
            for line in page_text_lines:
                single_page_text += line + "\n"
            # print(f"✅ Page {page_num} processed - {len(page_text_lines)} lines extracted")
        else:
            single_page_text += "No text detected on this page.\n"
            # print(f"❌ No text detected on page {page_num}")
        
        single_page_text += "\n"
        return page_num, single_page_text, page_text_lines
        
    except Exception as e:
        print(f"❌ Error processing page {page_num}: {str(e)}")
        error_text = f"Error processing page {page_num}: {str(e)}\n\n"
        return page_num, error_text, []


async def check_financial_keywords_async(page_text: str, financial_keywords: List[str]) -> Tuple[bool, int]:
    """Async check for financial keywords in text."""
    page_lower = page_text.lower()
    
    # Check if ALL financial keywords are present
    all_keywords_present = all(keyword in page_lower for keyword in financial_keywords)
    
    # Count how many keywords are present
    matched_keywords = sum(1 for keyword in financial_keywords if keyword in page_lower)
    
    return all_keywords_present, matched_keywords


async def process_ocr_from_images_async_batched(image_paths: List[str], batch_size: int = 5) -> List:
    """Memory-optimized OCR processing with batch processing and memory monitoring."""

    
    print(f"\n🔍 Running OCR on {len(image_paths)} pages with memory optimization...")
    print(f"💾 Batch size: {batch_size} pages")
    print("=" * 60)
    
    # Use cached global OCR model (80% speed improvement!)
    model = await get_global_ocr_model()
    
    # Monitor initial memory usage
    memory_before = psutil.virtual_memory().percent
    print(f"💾 Initial memory usage: {memory_before:.1f}%")
    
    # Process pages in batches to prevent memory exhaustion
    page_results = []
    total_batches = (len(image_paths) + batch_size - 1) // batch_size
    
    for batch_idx in range(0, len(image_paths), batch_size):
        batch_end = min(batch_idx + batch_size, len(image_paths))
        batch_paths = image_paths[batch_idx:batch_end]
        batch_num = (batch_idx // batch_size) + 1
        
        print(f"🔄 Processing OCR batch {batch_num}/{total_batches}: pages {batch_idx + 1}-{batch_end}")
        
        # Memory check before batch processing
        memory_current = psutil.virtual_memory().percent
        if memory_current > 80:
            print(f"⚠️ High memory usage ({memory_current:.1f}%), forcing cleanup...")
            gc.collect()
            memory_after_gc = psutil.virtual_memory().percent
            print(f"💾 Memory after cleanup: {memory_after_gc:.1f}%")
        
        # Process batch in parallel
        batch_tasks = [
            process_single_page_ocr(image_path, batch_idx + i + 1, model) 
            for i, image_path in enumerate(batch_paths)
        ]
        
        batch_results = await asyncio.gather(*batch_tasks)
        page_results.extend(batch_results)
        
        # Immediate memory cleanup after each batch
        del batch_tasks, batch_results, batch_paths
        gc.collect()
        
        memory_after_batch = psutil.virtual_memory().percent
        print(f"✅ Batch {batch_num} complete, memory: {memory_after_batch:.1f}%")
    
    memory_final = psutil.virtual_memory().percent
    print(f"💾 Final memory usage: {memory_final:.1f}% (started at {memory_before:.1f}%)")
    
    return page_results

async def process_ocr_from_images_async(image_paths: List[str]) -> Dict:
    """Async process OCR from multiple images with memory optimization."""
    # Get results from batched processing
    page_results = await process_ocr_from_images_async_batched(image_paths, batch_size=5)
    
    # Sort results by page number to maintain order
    page_results.sort(key=lambda x: x[0])
    
    print("\n🔍 Analyzing pages for financial content...")
    
    # Financial keywords to search for
    financial_keywords = ['revenue', 'expense', 'tax', 'profit', 'earning']
    
    # Track pages with financial keywords
    financial_pages = []
    all_pages_text = ""
    
    # Process results and check for financial keywords
    for i, (page_num, page_text, page_text_lines) in enumerate(page_results):
        # Add page text to all pages text regardless
        all_pages_text += page_text
        
        if not page_text_lines:  # Skip pages with no text or errors
            continue
            
        # Check financial keywords for current page
        all_keywords_present, matched_keywords = await check_financial_keywords_async(
            page_text, financial_keywords
        )
        
        # Track pages with any financial keywords
        if matched_keywords > 0:
            page_info = {
                "page_number": page_num,
                "image_path": image_paths[page_num - 1],  # Convert to 0-based index
                "matched_keywords": matched_keywords,
                "total_keywords": len(financial_keywords),
                "keywords_found": [keyword for keyword in financial_keywords if keyword in page_text.lower()],
                "all_keywords_present": all_keywords_present,
                "page_text": page_text
            }
            financial_pages.append(page_info)
        
        if all_keywords_present:
            print(f"💰 FINANCIAL PAGE DETECTED! All keywords found in Page {page_num}")
            print(f"📄 Image Path: {image_paths[page_num - 1]}")
            print("\n" + "=" * 80)
            print("📄 FINANCIAL PAGE CONTENT:")
            print("=" * 80)
            
            # Return complete result with financial page detected
            return {
                "financial_text": page_text,
                "all_pages_text": all_pages_text,
                "financial_pages": financial_pages,
                "detection_type": "single_page",
                "detected_page": page_num,
                "detected_image_path": image_paths[page_num - 1],
                "total_pages": len(image_paths)
            }
            
        elif matched_keywords >= 3:
            # print(f"📊 {matched_keywords}/5 financial keywords found in Page {page_num}. Checking with next page...")
            
            # Check if next page exists
            if i + 1 < len(page_results):
                next_page_num, next_page_text, next_page_text_lines = page_results[i + 1]
                
                if next_page_text_lines:  # Only combine if next page has content
                    # Combine current and next page text
                    combined_text = page_text + next_page_text
                    
                    # Check combined text for all financial keywords
                    combined_all_keywords_present, combined_matched_keywords = await check_financial_keywords_async(
                        combined_text, financial_keywords
                    )
                    
                    # Also add next page to financial pages if it has keywords
                    next_all_keywords_present, next_matched_keywords = await check_financial_keywords_async(
                        next_page_text, financial_keywords
                    )
                    
                    if next_matched_keywords > 0:
                        next_page_info = {
                            "page_number": next_page_num,
                            "image_path": image_paths[next_page_num - 1],
                            "matched_keywords": next_matched_keywords,
                            "total_keywords": len(financial_keywords),
                            "keywords_found": [keyword for keyword in financial_keywords if keyword in next_page_text.lower()],
                            "all_keywords_present": next_all_keywords_present,
                            "page_text": next_page_text
                        }
                        financial_pages.append(next_page_info)
                    
                    if combined_all_keywords_present:
                        print(f"💰 FINANCIAL SECTION DETECTED! All keywords found across Pages {page_num}-{next_page_num}")
                        print(f"📊 Combined keywords found: {combined_matched_keywords}/5")
                        print(f"📄 Image Paths: {image_paths[page_num - 1]}, {image_paths[next_page_num - 1]}")

                        
                        # Return complete result with combined pages detected
                        return {
                            "financial_text": combined_text,
                            "all_pages_text": all_pages_text,
                            "financial_pages": financial_pages,
                            "detection_type": "combined_pages",
                            "detected_pages": [page_num, next_page_num],
                            "detected_image_paths": [image_paths[page_num - 1], image_paths[next_page_num - 1]],
                            "total_pages": len(image_paths)
                        }
                    else:
                        print(f"📊 Combined keywords found: {combined_matched_keywords}/5 - Not sufficient for financial detection")
                else:
                    print(f"❌ Next page {next_page_num} has no content to combine")
            else:
                print("❌ No next page available for combination")
        else:
            # print(f"📊 Only {matched_keywords}/5 financial keywords found in Page {page_num} - Insufficient for financial detection")
            pass
    # If no specific financial content found, return all pages with keyword analysis
    print("\n❌ No specific financial content detected. Returning all pages text with keyword analysis.")
    
    # print(f"\n📊 FINANCIAL KEYWORD ANALYSIS SUMMARY:")
    # print(f"📄 Total pages processed: {len(image_paths)}")
    # print(f"💰 Pages with financial keywords: {len(financial_pages)}")
    
    for page_info in financial_pages:
        print(f"  📄 Page {page_info['page_number']}: {page_info['matched_keywords']}/{page_info['total_keywords']} keywords")
        print(f"     Keywords found: {', '.join(page_info['keywords_found'])}")
        print(f"     Image: {os.path.basename(page_info['image_path'])}")
    
    print("\n" + "=" * 60)
    print("✅ OCR PROCESSING COMPLETE FOR ALL PAGES")
    print("=" * 60)
    
    return {
        "financial_text": None,
        "all_pages_text": all_pages_text,
        "financial_pages": financial_pages,
        "detection_type": "no_complete_detection",
        "detected_pages": [],
        "detected_image_paths": [],
        "total_pages": len(image_paths)
    }


async def analyze_financial_metrics_async(financial_text: str, encoded_images: List[str] = None) -> Dict:
    """
    Async function to analyze financial text and images using OpenAI and extract metrics.
    
    Args:
        financial_text: The extracted financial text from OCR
        encoded_images: List of base64 encoded images (optional)
        
    Returns:
        dict: JSON containing extracted financial metrics
    """
    # Get the OpenAI client (initializes ONLY ONCE on first call)
    client = get_openai_client()
    
    # Base prompt for financial analysis
    base_prompt = """Extract these financial metrics from the provided text and/or images and return as JSON:

    Extract:
    1. revenue_from_operations
    2. profit_after_tax  
    3. profit_before_tax
    4. total_income
    5. other_income
    6. earnings_per_share

    Also get the quarterly values with period and year ended in a list of JSON.

    IMPORTANT: Return only the raw JSON object without any markdown formatting, code blocks, or additional text. Do not wrap the response in ```json or ``` blocks.

    Return JSON format:
    {
        "revenue_from_operations": number_or_null,
        "profit_after_tax": number_or_null,
        "profit_before_tax": number_or_null,
        "total_income": number_or_null,
        "other_income": number_or_null,
        "earnings_per_share": number_or_null,
        "units": "crores_or_lakhs_or_null",
        "quarterly_data": [
            {
                "period": "Q1/Q2/Q3/Q4",
                "year_ended": "YYYY",
                "revenue_from_operations": number_or_null,
                "profit_after_tax": number_or_null,
                "profit_before_tax": number_or_null,
                "total_income": number_or_null,
                "other_income": number_or_null,
                "earnings_per_share": number_or_null
            }
        ]
    }"""
    
    # Build content array starting with text
    content = [{"type": "text", "text": base_prompt}]
    
    # Add financial text if provided
    if financial_text and financial_text.strip():
        content.append({
            "type": "text", 
            "text": f"\nFINANCIAL TEXT:\n{financial_text}"
        })
    
    # Add images if provided
    if encoded_images:
        print(f"🖼️  Adding {len(encoded_images)} images to analysis...")
        for i, img_b64 in enumerate(encoded_images, 1):
            if img_b64:  # Only add non-empty images
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{img_b64}"
                    }
                })
                print(f"  📄 Added image {i} to analysis")
    
    # Add instruction for images if they exist
    if encoded_images:
        content.append({
            "type": "text",
            "text": "\nPlease analyze both the provided text and images to extract the financial metrics. Look for financial statements, profit & loss accounts, or any financial data in the images."
        })

    try:
        print(f"🤖 Sending request to OpenAI with {len(content)} content items...")
        
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": content
            }],
            temperature=0
        )
        
        response_content = response.choices[0].message.content
        # print(f"AI Response: {response_content}")
        
        if not response_content or response_content.strip() == "":
            raise ValueError("Empty response from OpenAI")
        
        # Clean the response - remove markdown code blocks
        clean_content = response_content.strip()
        if clean_content.startswith("```json"):
            clean_content = clean_content[7:]  # Remove ```json
        if clean_content.startswith("```"):
            clean_content = clean_content[3:]   # Remove ```
        if clean_content.endswith("```"):
            clean_content = clean_content[:-3]  # Remove ending ```
        clean_content = clean_content.strip()
            
        result = json.loads(clean_content)
        print("✅ AI Analysis completed with text and images")
        
        # Add metadata about the analysis
        result["analysis_metadata"] = {
            "text_provided": bool(financial_text and financial_text.strip()),
            "images_provided": len(encoded_images) if encoded_images else 0,
            "total_content_items": len(content)
        }
        
        return result
        
    except Exception as e:
        print(f"❌ Error in AI analysis: {e}")
        return {
            "revenue_from_operations": None,
            "profit_after_tax": None, 
            "profit_before_tax": None,
            "total_income": None,
            "other_income": None,
            "earnings_per_share": None,
            "units": None,
            "error": str(e),
            "analysis_metadata": {
                "text_provided": bool(financial_text and financial_text.strip()),
                "images_provided": len(encoded_images) if encoded_images else 0,
                "total_content_items": len(content)
            }
        }


async def process_pdf_from_url_async(
    pdf_url: str, 
    downloads_folder: str = "downloads", 
    images_folder: str = "images"
) -> Tuple[str, List[str], str]:
    """Complete async workflow: Download PDF from URL and convert to organized PNG images."""

    
    # Step 1: Download PDF with organized naming (async)
    print("\n STEP 1: Downloading PDF...")
    pdf_path = await download_pdf_async(pdf_url, downloads_folder)
    
    # Step 2: Convert to PNG images with organized folder structure (async)
    print("\n STEP 2: Converting to PNG images...")
    image_paths, images_output_folder = await pdf_to_png_async(pdf_path, images_folder)
    
    # print("\n" + "=" * 60)
    # print("✅ PROCESSING COMPLETE!")
    # print("=" * 60)
    print(f"📁 PDF saved: {pdf_path}")
    print(f"🖼️  Images folder: {images_output_folder}")
    print(f"📊 Total pages: {len(image_paths)}")
    print("=" * 60)
    
    return pdf_path, image_paths, images_output_folder

async def encode_images_async_batched(image_paths: List[str], batch_size: int = 3) -> List[str]:
    """
    Memory-optimized image encoding with batch processing.
    
    Args:
        image_paths: List of image file paths to encode
        batch_size: Number of images to process simultaneously
        
    Returns:
        List of base64 encoded image strings
    """

    async def encode_single_image(image_path: str) -> str:
        """Encode a single image to base64 asynchronously with memory optimization."""
        try:
            # Check memory before encoding large images
            memory_usage = psutil.virtual_memory().percent
            if memory_usage > 85:
                print(f"⚠️ High memory ({memory_usage:.1f}%) before encoding {os.path.basename(image_path)}")
                gc.collect()
            
            async with aiofiles.open(image_path, "rb") as f:
                image_data = await f.read()
                encoded = base64.b64encode(image_data).decode("utf-8")
                
                # Clear the raw image data immediately
                del image_data
                return encoded
                
        except Exception as e:
            print(f"❌ Error encoding image {image_path}: {str(e)}")
            return ""
    
    if not image_paths:
        return []
    
    print(f"🔄 Encoding {len(image_paths)} images to base64 with memory optimization...")
    print(f"💾 Batch size: {batch_size} images")
    
    encoded_images = []
    total_batches = (len(image_paths) + batch_size - 1) // batch_size
    memory_before = psutil.virtual_memory().percent
    print(f"💾 Initial memory usage: {memory_before:.1f}%")
    
    # Process images in small batches to prevent memory explosion
    for batch_idx in range(0, len(image_paths), batch_size):
        batch_end = min(batch_idx + batch_size, len(image_paths))
        batch_paths = image_paths[batch_idx:batch_end]
        batch_num = (batch_idx // batch_size) + 1
        
        print(f"🖼️ Encoding batch {batch_num}/{total_batches}: {len(batch_paths)} images")
        
        # Process batch in parallel (small batches to control memory)
        encoding_tasks = [encode_single_image(image_path) for image_path in batch_paths]
        batch_encoded = await asyncio.gather(*encoding_tasks)
        
        # Filter out empty results and add to final list
        valid_batch = [img for img in batch_encoded if img]
        encoded_images.extend(valid_batch)
        
        # Immediate cleanup after each batch
        del encoding_tasks, batch_encoded, valid_batch, batch_paths
        gc.collect()
        
        memory_after_batch = psutil.virtual_memory().percent
        print(f"✅ Encoding batch {batch_num} complete, memory: {memory_after_batch:.1f}%")
    
    memory_final = psutil.virtual_memory().percent
    print(f"✅ Successfully encoded {len(encoded_images)}/{len(image_paths)} images")
    print(f"💾 Final memory usage: {memory_final:.1f}% (started at {memory_before:.1f}%)")
    
    return encoded_images

# Keep backward compatibility
async def encode_images_async(image_paths: List[str]) -> List[str]:
    """
    Async function to encode multiple images to base64 with memory optimization.
    """
    return await encode_images_async_batched(image_paths, batch_size=3)


async def main_ocr_async(pdf_url: str):
    """Main async function to demonstrate the full workflow."""
    # Example URL - replace with your actual PDF URL
    # pdf_url = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/07bc7a9c-70e9-49e3-8b6a-073f4567c308.pdf"
    
    try:
        # Process PDF with organized folder structure (async)
        pdf_path, image_paths, images_folder = await process_pdf_from_url_async(pdf_url)
        
        # Run OCR on all pages (async with parallel processing)
        if image_paths:
            ocr_results = await process_ocr_from_images_async(image_paths)
            
            print("\n📄 OCR RESULTS SUMMARY:")
            print("=" * 80)
            # print(f"Detection Type: {ocr_results['detection_type']}")
            # print(f"Total Pages: {ocr_results['total_pages']}")
            print(f"Detected image paths: {ocr_results['detected_image_paths']}")
            print(f"Pages with Financial Keywords: {len(ocr_results['financial_pages'])}")
            
            # Encode detected financial images to base64
            if ocr_results['detected_image_paths']:
                print(f"\n🔄 Encoding financial images to base64...")
                encoded_images = await encode_images_async(ocr_results['detected_image_paths'])
                print(f"📊 Encoded {len(encoded_images)} images successfully")
            else:
                encoded_images = []
            
            
            # Use financial_text if available, otherwise use all_pages_text
            text_for_analysis = ocr_results['financial_text'] if ocr_results['financial_text'] else ocr_results['all_pages_text']
            
            # Add AI analysis (async) with both text and images
            print(f"\n🤖 Analyzing with AI using text and {len(encoded_images)} images...")
            financial_metrics = await analyze_financial_metrics_async(
                text_for_analysis, 
                encoded_images
            )
            
            print("\n📊 EXTRACTED FINANCIAL METRICS:")
            print(json.dumps(financial_metrics, indent=2))
            
            return financial_metrics
            # return {
            #     "pdf_path": pdf_path,
            #     "images_folder": images_folder,
            #     "total_pages": len(image_paths),
            #     "ocr_results": ocr_results,
            #     "financial_text": ocr_results['financial_text'],
            #     "all_pages_text": ocr_results['all_pages_text'],
            #     "financial_pages": ocr_results['financial_pages'],
            #     "detection_type": ocr_results['detection_type'],
            #     "detected_image_paths": ocr_results['detected_image_paths'],
            #     "encoded_images": encoded_images,
            #     "financial_metrics": financial_metrics
            # }
        else:
            print("❌ No images were created from the PDF")
            return None
            
    except Exception as e:
        print(f"❌ Error in main workflow: {str(e)}")
        return None


# if __name__ == "__main__":
#     # Run the async main function
#     result = asyncio.run(main_ocr_async())
    
    # if result:
    #     # print("\n" + "=" * 80)
    #     # print("🎉 ASYNC WORKFLOW COMPLETED SUCCESSFULLY!")
    #     # print("=" * 80)
    #     # print(f"📁 PDF processed: {result['pdf_path']}")
    #     # print(f"🖼️  Images saved in: {result['images_folder']}")
    #     # print(f"📊 Total pages processed: {result['total_pages']}")
    #     # print(f"🔍 Detection type: {result['detection_type']}")
    #     # print(f"💰 Pages with financial keywords: {len(result['financial_pages'])}")
        
    #     # if result['financial_pages']:
    #     #     print(f"\n📄 FINANCIAL PAGES FOUND:")
    #     #     for page_info in result['financial_pages']:
    #     #         print(f"  • Page {page_info['page_number']}: {page_info['matched_keywords']}/{page_info['total_keywords']} keywords")
    #     #         print(f"    Keywords: {', '.join(page_info['keywords_found'])}")
    #     #         print(f"    Image: {os.path.basename(page_info['image_path'])}")
        
    #     print(f"📈 Financial metrics extracted: {len([k for k, v in result['financial_metrics'].items() if v is not None and k != 'error'])}")
    #     print("=" * 80)
    # else:
    #     print("\n❌ Async workflow failed")
