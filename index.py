import os
import base64
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from PIL import Image
from pyzbar.pyzbar import decode
import fitz  # PyMuPDF
import qrcode
from io import BytesIO
from typing import List
from uuid import uuid4
import httpx

app = FastAPI()

# Cria o diretório "upload" se não existir
UPLOAD_DIR = "upload"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/serpro-cnh-qr/")
async def serpro_cnh_qr(file: UploadFile = File(...), foto_pessoal: UploadFile = File(...), cpf: str = Form(...)):
    try:
        # Verifica se o arquivo é uma imagem ou PDF
        if file.content_type not in ["image/png", "image/jpeg", "application/pdf"]:
            raise HTTPException(status_code=400, detail="Formato de arquivo não suportado. Use PNG, JPEG ou PDF.")

        # Lê o arquivo do QR Code enviado
        contents = await file.read()

        # Gera um identificador único para o arquivo do QR Code
        unique_id = str(uuid4())
        file_extension = file.filename.split(".")[-1].upper()
        file_name = f"cnh_{unique_id}.{file_extension.lower()}"
        file_path = os.path.join(UPLOAD_DIR, file_name)

        # Salva o arquivo do QR Code na pasta 'upload'
        with open(file_path, "wb") as f:
            f.write(contents)

        # Converte o arquivo salvo em base64
        file_base64 = convert_file_to_base64(file_path)

        # Forçar o formato do QR Code para "PNG" ou "JPEG"
        qrcode_format = "PNG" if file_extension in ["PNG", "JPG", "JPEG"] else "JPEG"

        # Lê e salva a foto pessoal do usuário
        foto_extension = foto_pessoal.filename.split(".")[-1].lower()
        foto_file_name = f"foto_{cpf}{unique_id}.{foto_extension}"
        foto_file_path = os.path.join(UPLOAD_DIR, foto_file_name)

        # Salva a foto pessoal enviada diretamente
        with open(foto_file_path, "wb") as f:
            f.write(await foto_pessoal.read())

        # Converte a foto pessoal para base64 sem decodificação incorreta
        foto_pessoal_base64 = convert_file_to_base64(foto_file_path)

        # Força o formato como "JPG", "PNG" ou "PDF" dependendo da extensão da foto pessoal
        if foto_extension in ["jpg", "jpeg"]:
            biometria_format = "JPG"
        elif foto_extension == "png":
            biometria_format = "PNG"
        else:
            raise HTTPException(status_code=400, detail="Formato de foto pessoal não suportado. Use JPG ou PNG.")

        # Processa o arquivo do QR Code para detectar QR Codes
        if file.content_type in ["image/png", "image/jpeg"]:
            # Para imagens, abrir com PIL e tentar decodificar o QR Code
            image = Image.open(file_path)
            qrcode_data, qrcode_images_base64 = decode_qrcode_from_image(image)

        elif file.content_type == "application/pdf":
            # Para PDF, extrair imagens das páginas e tentar decodificar QR Code
            qrcode_data, qrcode_images_base64 = decode_qrcode_from_pdf(contents)

        # Verifica se encontrou algum QR Code
        if not qrcode_data:
            raise HTTPException(status_code=400, detail="Nenhum QR Code encontrado no arquivo.")

        # Utiliza o primeiro QR Code encontrado para a validação
        qrcode_base64 = qrcode_images_base64[0]

        # Faz a requisição para a API do Serpro
        url = "https://gateway.apiserpro.serpro.gov.br/datavalid-demonstracao/v4/pf-facial-qrcode"
        headers = {
            "accept": "application/json",
            "Authorization": "Bearer 06aef429-a981-3ec5-a1f8-71d38d86481e",  # Token exemplo, troque pelo seu válido
            "Content-Type": "application/json"
        }
        payload = {
            "cpf": cpf,
            "validacao": {
                "qrcode": {
                    "formato": qrcode_format,
                    "base64": qrcode_base64
                },
                "biometria_facial": {
                    "vivacidade": True,
                    "formato": biometria_format,
                    "base64": foto_pessoal_base64
                }
            }
        }

        try:
            # Faz a requisição para a API do Serpro
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload)
            
            # Verifica se a resposta foi bem-sucedida
            if response.status_code == 200:
                return response.json()
            else:
                try:
                    # Tenta decodificar a mensagem de erro em JSON
                    error_message = response.json()
                except ValueError:
                    # Se falhar, retorna o texto bruto
                    error_message = response.text

                raise HTTPException(status_code=response.status_code, detail=error_message)

        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"Erro na requisição à API Serpro: {str(e)}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao processar arquivo: {str(e)}")


def decode_qrcode_from_image(image: Image.Image) -> (List[str], List[str]):
    """Decodifica QR Code de uma imagem e retorna os dados e as imagens em base64."""
    qrcodes = decode(image)
    qrcode_data = []
    qrcode_images_base64 = []

    for qrcode in qrcodes:
        # Decodifica o texto do QR Code
        data = qrcode.data.decode("utf-8")
        qrcode_data.append(data)

        # Extrai a área do QR Code e converte para base64
        rect = qrcode.rect
        qrcode_image = image.crop((rect.left, rect.top, rect.left + rect.width, rect.top + rect.height))
        qrcode_images_base64.append(convert_image_to_base64(qrcode_image))

    return qrcode_data, qrcode_images_base64


def decode_qrcode_from_pdf(pdf_data: bytes) -> (List[str], List[str]):
    """Extrai e decodifica QR Codes de um PDF, retorna os dados e as imagens em base64."""
    qrcode_data = []
    qrcode_images_base64 = []

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
        data, images_base64 = decode_qrcode_from_image(image)
        qrcode_data.extend(data)
        qrcode_images_base64.extend(images_base64)
    
    pdf_document.close()
    return qrcode_data, qrcode_images_base64


def generate_qrcode_base64(data: str) -> str:
    """Gera um QR Code a partir de uma string e retorna em formato base64."""
    # Cria um objeto de QR Code
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    
    # Gera a imagem do QR Code
    img = qr.make_image(fill='black', back_color='white')
    
    # Converte a imagem para base64
    return convert_image_to_base64(img)


def convert_image_to_base64(image: Image.Image) -> str:
    """Converte uma imagem PIL para uma string base64."""
    buffered = BytesIO()
    image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode("utf-8")


def convert_file_to_base64(file_path: str) -> str:
    """Converte um arquivo para base64."""
    with open(file_path, "rb") as file:
        file_base64 = base64.b64encode(file.read()).decode()  # Corrigido para não usar .decode('utf-8')
    return file_base64


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
        
        # Converte o arquivo salvo em base64
        file_base64 = convert_file_to_base64(file_path)

        # Processa o arquivo para detectar QR Codes
        if file.content_type in ["image/png", "image/jpeg"]:
            # Para imagens, abrir com PIL e tentar decodificar o QR Code
            image = Image.open(file_path)
            qrcode_data, qrcode_images_base64 = decode_qrcode_from_image(image)

        elif file.content_type == "application/pdf":
            # Para PDF, extrair imagens das páginas e tentar decodificar QR Code
            qrcode_data, qrcode_images_base64 = decode_qrcode_from_pdf(contents)

        # Verifica se encontrou algum QR Code
        if not qrcode_data:
            return {
                "message": "Nenhum QR Code encontrado no arquivo.",
                "file_path": file_path,
                "file_base64": file_base64
            }

        # Gera um novo QR Code em base64 para cada QR Code detectado
        qrcode_base64_list = [generate_qrcode_base64(data) for data in qrcode_data]

        # Retorna o texto decodificado do QR Code, a localização do arquivo e as imagens extraídas
        return {
            "qrcode_data": qrcode_data,
            "qrcode_base64": qrcode_base64_list,
            "qrcode_images_base64": qrcode_images_base64,
            "file_path": file_path,
            "file_base64": file_base64
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao processar arquivo: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
