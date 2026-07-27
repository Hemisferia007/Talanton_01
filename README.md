# Talanton

Motor de generación de leads para consultora de RRHH especializada en selección.

Detecta empresas con **búsquedas abiertas que no logran cerrar** —el momento exacto en
que necesitan una consultora— a partir de señales públicas de contratación, y las
prioriza con un score explicable.

## Estado

Fase de diseño. La estrategia, arquitectura y roadmap están en
[`docs/estrategia-leads.md`](docs/estrategia-leads.md).

## Idea en una línea

El activo no es el scraper, es la **serie histórica**: saber que un aviso lleva 52 días
publicado y ya se republicó dos veces sólo es posible si venís mirando desde antes.

## Stack previsto

Python 3.11+ · [Scrapling](https://github.com/D4Vinci/Scrapling) (ingesta y parseo
adaptativo) · Pydantic · Postgres · FastAPI
