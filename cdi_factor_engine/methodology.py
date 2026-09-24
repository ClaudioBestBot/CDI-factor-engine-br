"""Identificação e versionamento da metodologia de cálculo.

Enquanto não houver confirmação por documentação oficial e golden cases
independentes, a metodologia deste motor é classificada explicitamente
como uma reconstrução própria (não oficial), sem afiliação com B3/CETIP.
"""

from __future__ import annotations

#: Identificador de metodologia retornado em todo resultado de cálculo.
#: Não representa a metodologia oficial B3/CETIP.
METHODOLOGY_VERSION = "legacy-reconstructed/max-precision-v1"

#: Único modo de precisão suportado nesta etapa: sem arredondamento
#: intermediário diário, truncagem apenas no resultado operacional.
PRECISION_MODE_MAX = "MAX_PRECISION"
