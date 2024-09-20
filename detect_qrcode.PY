import os
import base64
from fastapi import FastAPI, File, UploadFile, HTTPException
from PIL import Image
from pyzbar.pyzbar import decode
import fitz  # PyMuPDF
import qrcode
from io import BytesIO
from typing import List
from uuid import uuid4

app = FastAPI()

# Cria o diretório "upload" se não existir
UPLOAD_DIR = "upload"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/detect-qrcode/")
async def detect_qrcode(file: UploadFile = File(...)):
    try:
        # Verifica se o arquivo é uma imagem ou PDF
        if file.content_type not in ["image/png", "image/jpeg", "application/pdf"]:
            raise HTTPException(status_code=400, detail="Formato de arquivo não suportado. Use PNG, JPEG ou PDF.")
        
        # Lê o arquivo enviado
        contents = await file.read()
        
        # Gera um identificador único para o arquivo
        unique_id = str(uuid4())
        file_extension = file.filename.split(".")[-1]
        file_name = f"cnh_{unique_id}.{file_extension}"
        file_path = os.path.join(UPLOAD_DIR, file_name)
        
        # Salva o arquivo na pasta 'upload'
        with open(file_path, "wb") as f:
            f.write(contents)
        
        # Processa o arquivo para detectar QR Codes
        if file.content_type in ["image/png", "image/jpeg"]:
            # Para imagens, abrir com PIL e tentar decodificar o QR Code
            image = Image.open(file_path)
            qrcode_data = decode_qrcode_from_image(image)

        elif file.content_type == "application/pdf":
            # Para PDF, extrair imagens das páginas e tentar decodificar QR Code
            qrcode_data = decode_qrcode_from_pdf(contents)

        # Verifica se encontrou algum QR Code
        if not qrcode_data:
            return {
                "message": "Nenhum QR Code encontrado no arquivo.",
                "file_path": file_path
            }

        # Gera um novo QR Code em base64 para cada QR Code detectado
        qrcode_base64_list = [generate_qrcode_base64(data) for data in qrcode_data]

        # Retorna o texto decodificado do QR Code, o QR Code gerado em base64 e a localização do arquivo
        return {
            "qrcode_data": qrcode_data,
            "file_path": file_name,
            "qrcode_base64": qrcode_base64_list
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao processar arquivo: {str(e)}")


def decode_qrcode_from_image(image: Image.Image) -> List[str]:
    """Decodifica QR Code de uma imagem."""
    qrcodes = decode(image)
    return [qrcode.data.decode("utf-8") for qrcode in qrcodes]


def decode_qrcode_from_pdf(pdf_data: bytes) -> List[str]:
    """Extrai e decodifica QR Codes de um PDF."""
    qrcode_data = []
    # Abre o PDF com PyMuPDF
    pdf_document = fitz.open(stream=pdf_data, filetype="pdf")
    
    # Itera por cada página do PDF
    for page_num in range(pdf_document.page_count):
        page = pdf_document[page_num]
        
        # Converte a página para imagem (matriz de pixels)
        pix = page.get_pixmap()
        
        # Cria uma imagem PIL a partir da matriz de pixels
        image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        
        # Decodifica QR Codes da imagem
        qrcode_data.extend(decode_qrcode_from_image(image))
    
    pdf_document.close()
    return qrcode_data


def generate_qrcode_base64(data: str) -> str:
    """Gera um QR Code a partir de uma string e retorna em formato base64."""
    # Cria um objeto de QR Code
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    
    # Gera a imagem do QR Code
    img = qr.make_image(fill='black', back_color='white')
    
    # Converte a imagem para base64
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
    
    return img_base64

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
