import os
import mimetypes
from datetime import datetime
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    Response,
    jsonify
)
from werkzeug.utils import secure_filename
# .env dosyasını yükle (varsa)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Azure SDK
try:
    from azure.storage.blob import BlobServiceClient, ContentSettings
    from azure.core.exceptions import AzureError, ResourceNotFoundError, ResourceExistsError
    AZURE_SDK_AVAILABLE = True
except ImportError:
    BlobServiceClient = None
    ContentSettings = None
    AzureError = Exception
    ResourceNotFoundError = Exception
    ResourceExistsError = Exception
    AZURE_SDK_AVAILABLE = False

app = Flask(__name__)

# Konfigürasyon
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "mini-drive-bulut-bilisim-secret-key-2026")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB limit

# Ortam Değişkenleri
AZURE_STORAGE_CONNECTION_STRING = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "").strip()
CONTAINER_NAME = os.environ.get("CONTAINER_NAME", "drive").strip() or "drive"
PORT = int(os.environ.get("PORT", "80"))


def format_size(size_bytes: int) -> str:
    """Byte cinsinden dosya boyutunu okunabilir formata (B, KB, MB, GB) çevirir."""
    if size_bytes is None:
        return "0 B"
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size_bytes} B"


def get_file_type_meta(filename: str) -> dict:
    """Dosya uzantısına göre ikon tipi ve renk grubu belirler."""
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    
    image_exts = {"jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "ico"}
    doc_exts = {"doc", "docx", "odt", "rtf", "txt", "md"}
    sheet_exts = {"xls", "xlsx", "csv", "ods"}
    pres_exts = {"ppt", "pptx", "odp"}
    archive_exts = {"zip", "rar", "7z", "tar", "gz", "bz2"}
    code_exts = {"py", "js", "html", "css", "json", "xml", "sql", "sh", "yaml", "yml"}
    video_exts = {"mp4", "mkv", "avi", "mov", "webm"}
    audio_exts = {"mp3", "wav", "ogg", "flac"}

    if ext == "pdf":
        return {"category": "pdf", "badge": "PDF", "color": "rose"}
    if ext in image_exts:
        return {"category": "image", "badge": ext.upper(), "color": "indigo"}
    if ext in doc_exts:
        return {"category": "document", "badge": ext.upper(), "color": "sky"}
    if ext in sheet_exts:
        return {"category": "sheet", "badge": ext.upper(), "color": "emerald"}
    if ext in pres_exts:
        return {"category": "presentation", "badge": ext.upper(), "color": "amber"}
    if ext in archive_exts:
        return {"category": "archive", "badge": ext.upper(), "color": "orange"}
    if ext in code_exts:
        return {"category": "code", "badge": ext.upper(), "color": "violet"}
    if ext in video_exts:
        return {"category": "video", "badge": ext.upper(), "color": "purple"}
    if ext in audio_exts:
        return {"category": "audio", "badge": ext.upper(), "color": "teal"}

    return {"category": "other", "badge": ext.upper() if ext else "FILE", "color": "slate"}


def clean_filename(filename: str) -> str:
    """
    Güvenli dosya adı oluşturur.
    Path traversal (../) engellenir, Türkçe karakterler korunur.
    """
    # Sadece dosya adını al (dizin yolunu temizle)
    clean_name = os.path.basename(filename).strip()
    clean_name = clean_name.replace("/", "").replace("\\", "")
    if not clean_name or clean_name in {".", ".."}:
        clean_name = f"dosya_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return clean_name


def get_blob_clients():
    """
    BlobServiceClient ve ContainerClient nesnelerini döndürür.
    Container mevcut değilse otomatik olarak oluşturur (Sınıf içi hata önleme).
    Hata durumunda (None, None, "Hata Mesajı") döner.
    """
    if not AZURE_SDK_AVAILABLE:
        return None, None, "azure-storage-blob kütüphanesi yüklü değil."

    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", AZURE_STORAGE_CONNECTION_STRING).strip()
    container_name = os.environ.get("CONTAINER_NAME", CONTAINER_NAME).strip() or "drive"

    if not conn_str:
        return None, None, "AZURE_STORAGE_CONNECTION_STRING ortam değişkeni tanımlanmamış."

    try:
        service_client = BlobServiceClient.from_connection_string(conn_str)
        container_client = service_client.get_container_client(container_name)

        # Container yoksa otomatik oluştur
        try:
            if not container_client.exists():
                container_client.create_container()
        except ResourceExistsError:
            pass

        return service_client, container_client, None

    except AzureError as ae:
        return None, None, f"Azure Storage bağlantı hatası: {str(ae)}"
    except ValueError as ve:
        return None, None, f"Bağlantı dizesi formatı geçersiz: {str(ve)}"
    except Exception as e:
        return None, None, f"Beklenmeyen bir hata oluştu: {str(e)}"


# -------------------------------------------------------------
# Endpoint'ler
# -------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health_check():
    """Azure Container Instances (ACI) liveness/readiness kontrolü."""
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", AZURE_STORAGE_CONNECTION_STRING).strip()
    container_name = os.environ.get("CONTAINER_NAME", CONTAINER_NAME).strip() or "drive"
    
    return jsonify({
        "status": "ok",
        "service": "Mini Drive",
        "container_name": container_name,
        "connection_configured": bool(conn_str)
    }), 200


@app.route("/", methods=["GET"])
def index():
    """Ana sayfa: Dosyaları listeler veya bağlantı hatası uyarısı gösterir."""
    container_name = os.environ.get("CONTAINER_NAME", CONTAINER_NAME).strip() or "drive"
    service_client, container_client, error_message = get_blob_clients()

    if error_message:
        return render_template(
            "index.html",
            files=[],
            container_name=container_name,
            total_count=0,
            total_size_formatted="0 B",
            connection_error=error_message,
        )

    files = []
    total_size = 0

    try:
        blobs = container_client.list_blobs()
        for blob in blobs:
            blob_size = blob.size or 0
            total_size += blob_size

            # Son güncelleme tarihi formatlama
            last_mod_str = "-"
            if blob.last_modified:
                last_mod_str = blob.last_modified.strftime("%d.%m.%Y %H:%M")

            meta = get_file_type_meta(blob.name)

            files.append({
                "name": blob.name,
                "size": blob_size,
                "size_formatted": format_size(blob_size),
                "last_modified": last_mod_str,
                "last_modified_raw": blob.last_modified.timestamp() if blob.last_modified else 0,
                "meta": meta
            })

        # En son yüklenen en üstte listelensin
        files.sort(key=lambda x: x["last_modified_raw"], reverse=True)

        return render_template(
            "index.html",
            files=files,
            container_name=container_name,
            total_count=len(files),
            total_size_formatted=format_size(total_size),
            connection_error=None,
        )

    except AzureError as ae:
        return render_template(
            "index.html",
            files=[],
            container_name=container_name,
            total_count=0,
            total_size_formatted="0 B",
            connection_error=f"Dosyalar listelenirken Azure hatası oluştu: {str(ae)}",
        )
    except Exception as e:
        return render_template(
            "index.html",
            files=[],
            container_name=container_name,
            total_count=0,
            total_size_formatted="0 B",
            connection_error=f"Dosyalar listelenirken genel hata oluştu: {str(e)}",
        )


@app.route("/upload", methods=["POST"])
def upload_files():
    """Çoklu veya tekli dosya yükleme (overwrite=True, max 50 MB)."""
    _, container_client, error_message = get_blob_clients()
    if error_message:
        flash(f"Dosya yüklenemedi: {error_message}", "error")
        return redirect(url_for("index"))

    # 'files' veya 'file' anahtarlarını kontrol et
    uploaded_files = request.files.getlist("files")
    if not uploaded_files or (len(uploaded_files) == 1 and not uploaded_files[0].filename):
        single_file = request.files.get("file")
        if single_file and single_file.filename:
            uploaded_files = [single_file]
        else:
            flash("Lütfen yüklemek için en az bir dosya seçin.", "warning")
            return redirect(url_for("index"))

    success_count = 0
    errors = []

    for file_storage in uploaded_files:
        if not file_storage or not file_storage.filename:
            continue

        raw_filename = file_storage.filename
        safe_name = clean_filename(raw_filename)

        # MIME tipini belirle
        content_type, _ = mimetypes.guess_type(safe_name)
        if not content_type:
            content_type = file_storage.content_type or "application/octet-stream"

        content_settings = ContentSettings(content_type=content_type)

        try:
            blob_client = container_client.get_blob_client(safe_name)
            # Dosyayı stream olarak Azure'a yükle (overwrite=True)
            blob_client.upload_blob(
                file_storage.stream,
                overwrite=True,
                content_settings=content_settings,
                max_concurrency=4
            )
            success_count += 1
        except AzureError as ae:
            errors.append(f"'{safe_name}': {str(ae)}")
        except Exception as e:
            errors.append(f"'{safe_name}': {str(e)}")

    if success_count > 0:
        if success_count == 1:
            flash("1 dosya Azure Blob Storage'a başarıyla yüklendi.", "success")
        else:
            flash(f"{success_count} dosya Azure Blob Storage'a başarıyla yüklendi.", "success")

    if errors:
        for err in errors:
            flash(f"Yükleme hatası: {err}", "error")

    return redirect(url_for("index"))


@app.route("/download/<path:filename>", methods=["GET"])
def download_file(filename: str):
    """
    Dosyayı Azure Blob Storage'dan stream ederek indirir (Proxy mantığı).
    Container erişim seviyesi 'Private' olsa bile çalışır.
    """
    safe_name = clean_filename(filename)
    _, container_client, error_message = get_blob_clients()
    if error_message:
        flash(f"İndirme başarısız: {error_message}", "error")
        return redirect(url_for("index"))

    try:
        blob_client = container_client.get_blob_client(safe_name)
        blob_properties = blob_client.get_blob_properties()
        download_stream = blob_client.download_blob()

        content_type = (
            blob_properties.content_settings.content_type
            or mimetypes.guess_type(safe_name)[0]
            or "application/octet-stream"
        )

        # Chunks ile stream yanıtı döndür
        response = Response(
            download_stream.chunks(),
            mimetype=content_type,
            direct_passthrough=True
        )
        
        # Tarayıcı indirmesi için Content-Disposition başlığı
        response.headers["Content-Disposition"] = f'attachment; filename="{safe_name}"'
        if blob_properties.size:
            response.headers["Content-Length"] = str(blob_properties.size)

        return response

    except ResourceNotFoundError:
        flash(f"'{safe_name}' adlı dosya Azure Blob Storage'da bulunamadı.", "error")
        return redirect(url_for("index"))
    except AzureError as ae:
        flash(f"Dosya indirilirken Azure hatası: {str(ae)}", "error")
        return redirect(url_for("index"))
    except Exception as e:
        flash(f"Dosya indirilirken hata oluştu: {str(e)}", "error")
        return redirect(url_for("index"))


@app.route("/delete/<path:filename>", methods=["POST"])
def delete_file(filename: str):
    """İlgili blob'u Azure Storage'dan siler."""
    safe_name = clean_filename(filename)
    _, container_client, error_message = get_blob_clients()
    if error_message:
        flash(f"Silme başarısız: {error_message}", "error")
        return redirect(url_for("index"))

    try:
        blob_client = container_client.get_blob_client(safe_name)
        blob_client.delete_blob()
        flash(f"'{safe_name}' adlı dosya başarıyla silindi.", "success")
    except ResourceNotFoundError:
        flash(f"'{safe_name}' adlı dosya zaten mevcut değil.", "warning")
    except AzureError as ae:
        flash(f"Dosya silinirken Azure hatası: {str(ae)}", "error")
    except Exception as e:
        flash(f"Dosya silinirken hata oluştu: {str(e)}", "error")

    return redirect(url_for("index"))


@app.errorhandler(413)
def request_entity_too_large(error):
    """Maksimum dosya boyutu (50 MB) aşıldığında çağrılır."""
    flash("Dosya boyutu 50 MB sınırını aşıyor! Lütfen daha küçük bir dosya yükleyin.", "error")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
