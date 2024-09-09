"""This module defines the FastAPI endpoint for converting a PDF document to PNG images."""

import os

import fitz
from app.common.aws import load_pdf_from_aws, upload_file_to_s3
from app.common.config import config
from app.common.schemas import PNGResponse
from fastapi import Form, HTTPException


def create_pngs(aws_filename: str = Form(...)):
    """Convert a PDF document to PNG images. Please note that this function will overwrite any existing PNG files.

    Args:
        aws_filename (str): The name of the PDF document in the S3 bucket. For example, "pdfs/10012.pdf".

    Returns:
        PNGResponse: The URLs of the PNG images in the S3 bucket.
    """
    # Validate the filename parameter
    if not aws_filename or not isinstance(aws_filename, str):
        raise HTTPException(
            status_code=400, detail="Invalid request. 'filename' parameter is required and must be a string."
        )

    # Check if the PDF name is valid
    if not aws_filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Invalid request. The filename must end with '.pdf'.")
    if not aws_filename.startswith("pdfs/"):
        raise HTTPException(status_code=400, detail="Invalid request. The filename must start with 'pdfs/'.")

    # Get the filename from the path
    filename = aws_filename.replace("pdfs/", "").replace(".pdf", "")

    # Initialize the S3 client
    pdf_document = load_pdf_from_aws(aws_filename)

    png_urls = []

    # Convert each page of the PDF to PNG
    try:
        for page_number in range(pdf_document.page_count):
            page = pdf_document.load_page(page_number)
            pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))
            png_filename = f"{filename}-{page_number + 1}.png"
            png_path = f"/tmp/{png_filename}"  # Local path to save the PNG
            s3_bucket_png_path = f"pngs/{png_filename}"

            pix.save(png_path)

            # Upload the PNG to S3
            upload_file_to_s3(
                png_path,  # The local path to the file to upload
                s3_bucket_png_path,  # The key (name) of the file in the bucket
            )

            # Generate the S3 URL
            png_url = f"https://{config.bucket_name}.s3.amazonaws.com/{s3_bucket_png_path}"
            png_urls.append(png_url)

            # Clean up the local file
            os.remove(png_path)
    except Exception:
        raise HTTPException(status_code=500, detail="An error occurred while processing the PDF.") from None

    return PNGResponse(png_urls=png_urls)
