"""Serviço de processamento de imagens — remoção de fundo e fundo branco."""

import logging
from io import BytesIO
from pathlib import Path

from PIL import Image as PILImage
from rembg import remove

logger = logging.getLogger(__name__)


def remove_background(input_path: str, output_path: str) -> str:
    """Remove o fundo da imagem e substitui por fundo branco.

    Args:
        input_path: caminho da imagem original.
        output_path: caminho onde salvar a imagem processada.

    Returns:
        O output_path se sucesso.

    Raises:
        RuntimeError: se o processamento falhar.
    """
    try:
        with open(input_path, "rb") as f:
            input_data = f.read()

        # Remove fundo — retorna PNG com transparência
        result_data = remove(input_data)

        # Abre a imagem com transparência e cola sobre fundo branco
        img_rgba = PILImage.open(BytesIO(result_data)).convert("RGBA")
        background = PILImage.new("RGBA", img_rgba.size, (255, 255, 255, 255))
        background.paste(img_rgba, mask=img_rgba.split()[3])

        # Salva como JPEG (Mercado Livre prefere JPEG)
        img_rgb = background.convert("RGB")
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        img_rgb.save(output_path, "JPEG", quality=95)

        logger.info("Imagem processada: %s → %s", input_path, output_path)
        return output_path

    except Exception as exc:
        logger.error("Erro ao processar imagem %s: %s", input_path, exc)
        raise RuntimeError(f"Falha ao processar imagem: {exc}") from exc
