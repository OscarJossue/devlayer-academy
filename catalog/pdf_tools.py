"""Herramientas para materiales PDF privados.

Principios:
- Nunca se convierte el PDF a texto para el alumno.
- El PDF original se optimiza como PDF conservando páginas, tipografía, vectores e imágenes.
- El archivo privado no se expone directamente: el alumno recibe una imagen renderizada
  de una sola página cada vez, con autorización de matrícula en la vista de learning.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

MAX_SOURCE_BYTES = 40 * 1024 * 1024
MAX_OPTIMIZED_BYTES = 20 * 1024 * 1024
MAX_PAGES = 120


class PDFMaterialError(Exception):
    pass


def _run(command: list[str], timeout: int = 45) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise PDFMaterialError(
            'El servidor no tiene instaladas las herramientas PDF requeridas. Reconstruye Docker con Ghostscript y Poppler.'
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise PDFMaterialError('El PDF tardó demasiado en procesarse. Prueba optimizándolo antes de subirlo.') from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b'').decode('utf-8', errors='ignore').strip()
        raise PDFMaterialError(f'No se pudo procesar el PDF. {detail[-350:]}'.strip()) from exc


def _page_count_path(path: str | Path) -> int:
    result = _run(['pdfinfo', str(path)], timeout=20)
    text = result.stdout.decode('utf-8', errors='ignore')
    match = re.search(r'^Pages:\s+(\d+)\s*$', text, re.MULTILINE | re.IGNORECASE)
    if not match:
        raise PDFMaterialError('No se pudo determinar la cantidad de páginas del PDF.')
    pages = int(match.group(1))
    if pages < 1:
        raise PDFMaterialError('El PDF no contiene páginas válidas.')
    if pages > MAX_PAGES:
        raise PDFMaterialError(f'El PDF tiene {pages} páginas. El máximo permitido por material es {MAX_PAGES}.')
    return pages


def optimize_pdf_bytes(data: bytes, filename: str = 'material.pdf') -> tuple[bytes, dict]:
    """Comprime el PDF manteniéndolo como PDF. No extrae ni reescribe su contenido como texto."""
    if not data:
        raise PDFMaterialError('El PDF está vacío.')
    if len(data) > MAX_SOURCE_BYTES:
        raise PDFMaterialError('El PDF supera 40 MB antes de optimizarse.')

    with tempfile.TemporaryDirectory(prefix='academy-pdf-') as tmp:
        source = Path(tmp) / 'source.pdf'
        output = Path(tmp) / 'optimized.pdf'
        source.write_bytes(data)
        before_pages = _page_count_path(source)

        # Perfil orientado a lectura en pantalla: conserva la estructura PDF y sus páginas,
        # comprime fuentes/streams y reduce imágenes a una resolución razonable para curso.
        _run([
            'gs', '-sDEVICE=pdfwrite', '-dCompatibilityLevel=1.6',
            '-dNOPAUSE', '-dQUIET', '-dBATCH', '-dSAFER',
            '-dDetectDuplicateImages=true', '-dCompressFonts=true', '-dSubsetFonts=true',
            '-dPDFSETTINGS=/ebook',
            '-dDownsampleColorImages=true', '-dColorImageDownsampleType=/Bicubic', '-dColorImageResolution=110',
            '-dDownsampleGrayImages=true', '-dGrayImageDownsampleType=/Bicubic', '-dGrayImageResolution=110',
            '-dDownsampleMonoImages=true', '-dMonoImageDownsampleType=/Subsample', '-dMonoImageResolution=180',
            '-dJPEGQ=68', '-dAutoRotatePages=/None',
            f'-sOutputFile={output}', str(source),
        ], timeout=90)

        optimized = output.read_bytes()
        after_pages = _page_count_path(output)
        if after_pages != before_pages:
            raise PDFMaterialError('La optimización cambió la cantidad de páginas y fue descartada por seguridad.')

        # Si Ghostscript no logra reducirlo (común en PDFs ya muy pequeños), conservamos
        # el PDF original para evitar aumentar el almacenamiento.
        selected = optimized if len(optimized) < len(data) else data
        selected_size = len(selected)
        if selected_size > MAX_OPTIMIZED_BYTES:
            raise PDFMaterialError(
                f'El PDF sigue pesando {selected_size / 1024 / 1024:.1f} MB después de optimizarse. '
                'Reduce fotografías muy grandes antes de volver a cargarlo.'
            )

        safe_name = Path(filename or 'material.pdf').name
        if not safe_name.lower().endswith('.pdf'):
            safe_name += '.pdf'
        return selected, {
            'pages': before_pages,
            'original_size': len(data),
            'optimized_size': selected_size,
            'saved_bytes': max(0, len(data) - selected_size),
            'filename': safe_name,
        }


def optimize_pdf_upload(upload):
    from django.core.files.uploadedfile import SimpleUploadedFile
    upload.seek(0)
    data = upload.read()
    upload.seek(0)
    optimized, info = optimize_pdf_bytes(data, getattr(upload, 'name', 'material.pdf'))
    return SimpleUploadedFile(info['filename'], optimized, content_type='application/pdf'), info


@contextmanager
def local_pdf_path(field_file):
    """Entrega una ruta local aunque en el futuro el storage deje de ser FileSystemStorage."""
    try:
        path = field_file.path
    except (AttributeError, NotImplementedError, ValueError):
        path = None
    if path and Path(path).exists():
        yield str(path)
        return

    with tempfile.NamedTemporaryFile(prefix='academy-material-', suffix='.pdf', delete=False) as tmp:
        temp_name = tmp.name
        field_file.open('rb')
        try:
            shutil.copyfileobj(field_file, tmp)
        finally:
            field_file.close()
    try:
        yield temp_name
    finally:
        Path(temp_name).unlink(missing_ok=True)


def pdf_page_count(field_file) -> int:
    if not field_file:
        return 0
    with local_pdf_path(field_file) as path:
        return _page_count_path(path)


def render_pdf_page(field_file, page_number: int, *, width: int = 2200, quality: int = 88) -> bytes:
    """Renderiza UNA página bajo demanda para el visor horizontal del estudiante.

    No se guarda una segunda copia de las diapositivas en media; se conserva solo el PDF
    comprimido. La respuesta se renderiza con resolución suficiente para lectura a pantalla completa.
    """
    if not field_file:
        raise PDFMaterialError('La clase no tiene material PDF.')
    with local_pdf_path(field_file) as path:
        pages = _page_count_path(path)
        if page_number < 1 or page_number > pages:
            raise PDFMaterialError('Página fuera de rango.')
        with tempfile.TemporaryDirectory(prefix='academy-pdf-page-') as tmp:
            prefix = Path(tmp) / 'page'
            _run([
                'pdftoppm', '-f', str(page_number), '-l', str(page_number),
                '-singlefile', '-jpeg', '-jpegopt', f'quality={quality},progressive=y,optimize=y',
                '-scale-to-x', str(width), '-scale-to-y', '-1',
                str(path), str(prefix),
            ], timeout=35)
            output = prefix.with_suffix('.jpg')
            if not output.exists():
                raise PDFMaterialError('No se pudo generar la página del material.')
            return output.read_bytes()
