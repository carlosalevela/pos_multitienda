from .models import Categoria

def resolver_categoria(nombre_raw: str):
    """
    Busca o crea una categoría por nombre.
    Normaliza espacios múltiples e ignora mayúsculas/minúsculas.
    """
    nombre = ' '.join((nombre_raw or '').split()).strip()
    if not nombre:
        return None

    # Busca primero (case-insensitive)
    categoria = Categoria.objects.filter(nombre__iexact=nombre).first()
    if not categoria:
        categoria = Categoria.objects.create(nombre=nombre)
    return categoria