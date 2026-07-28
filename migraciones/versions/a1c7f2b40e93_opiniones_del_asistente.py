"""opiniones del asistente

Revision ID: a1c7f2b40e93
Revises: f488e8886cb2
Create Date: 2026-07-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a1c7f2b40e93'
down_revision: Union[str, Sequence[str], None] = 'f488e8886cb2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'opiniones',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('lead_id', sa.Integer(), nullable=False),
        sa.Column(
            'veredicto',
            sa.Enum('CONTACTAR', 'ESPERAR', 'DESCARTAR', name='veredicto'),
            nullable=False,
        ),
        sa.Column('confianza', sa.String(length=20), nullable=False),
        sa.Column('motivos', sa.Text(), nullable=False),
        sa.Column('reparos', sa.Text(), nullable=False),
        sa.Column('que_decir', sa.Text(), nullable=True),
        sa.Column('a_quien', sa.String(length=200), nullable=True),
        sa.Column('modelo', sa.String(length=60), nullable=False),
        sa.Column('firma_contexto', sa.String(length=40), nullable=False),
        sa.Column('creada_en', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    # Una opinión por lead: al volver a pedirla se pisa, no se acumula.
    op.create_index(op.f('ix_opiniones_lead_id'), 'opiniones', ['lead_id'], unique=True)
    op.create_index(op.f('ix_opiniones_veredicto'), 'opiniones', ['veredicto'])


def downgrade() -> None:
    op.drop_index(op.f('ix_opiniones_veredicto'), table_name='opiniones')
    op.drop_index(op.f('ix_opiniones_lead_id'), table_name='opiniones')
    op.drop_table('opiniones')
