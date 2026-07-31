"""Portales de empleo argentinos: descubrir empresas que están contratando hoy.

Es la vuelta que le faltaba al producto. El resto de los conectores **vigila**
empresas que ya cargaste; estos las **descubren**: se define un segmento —zona,
rubro, tamaño— y las empresas que aparecen publicando ya son leads con señal.
No hay que esperar a que publiquen, publicaron.

Por qué estos portales y no otros: acá postean las PyMEs argentinas. Greenhouse
y Lever los usan empresas de tecnología medianas y grandes; LinkedIn sesga a lo
mismo más las consultoras. Bumeran, ZonaJobs y Computrabajo son donde está el
mercado que compra búsquedas de mando medio.

Sobre los selectores: los portales cambian el HTML seguido. Cada conector
concentra sus selectores en constantes al principio del archivo para que
arreglarlos sea cambiar una línea, y Scrapling ya trae emparejamiento adaptativo
para amortiguar los cambios chicos. Aun así, **hay que verificarlos contra el
HTML real la primera vez**: se escribieron contra la estructura documentada de
cada sitio, no contra una respuesta capturada.
"""

from .base import PORTALES, Segmento, buscar_en_portales

__all__ = ["PORTALES", "Segmento", "buscar_en_portales"]
