# Образ eggent-plus с инструментами документов
#
# Базовый образ собирается из upstream отдельно:
#   git clone --depth 1 -b v0.8.0 https://github.com/eggent-ai/eggent.git upstream
#   cd upstream && docker build -t eggent-plus:base .
#
# Затем этот слой:
#   docker build -f docker/Dockerfile -t eggent-plus:documents .
#
# Сборка идёт на LXC <номер> (<ip сборщика>), не на VM <номер> с живым Eggent.

FROM eggent-plus:base

USER root
ENV DEBIAN_FRONTEND=noninteractive

# Инструменты, без которых агент не работает с документами из коробки:
#   tesseract + rus  — распознавание сканов и фото по-русски;
#   ghostscript      — сжатие PDF;
#   pandoc           — md <-> docx;
#   poppler-utils    — pdftoppm/pdfinfo для сканов и проверки страниц;
#   libreoffice      — docx/pptx/xlsx -> PDF и обратно;
#   matplotlib       — графики; DejaVu нужен для кириллицы в подписях.
#
# matplotlib ставится в venv приложения, а не пакетом python3-matplotlib: apt-версия собрана
# под системный numpy, а `python3` в образе — это /opt/eggent-python (numpy 2.4), и импорт падал
# с «numpy.core.multiarray failed to import».
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-rus \
    ghostscript \
    pandoc \
    poppler-utils \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    libreoffice-l10n-ru \
    fonts-dejavu-core \
  && rm -rf /var/lib/apt/lists/*

RUN /opt/eggent-python/bin/pip install --no-cache-dir matplotlib

# Кэш matplotlib. Проверки ниже идут от root и создают /app/data/.cache/matplotlib root-овым;
# приложение работает под node и получало предупреждение о незаписываемом кэше.
ENV MPLCONFIGDIR=/app/data/tmp/matplotlib

# Приёмка: каждый инструмент не только установлен, но и работает.
RUN tesseract --list-langs 2>&1 | grep -qx rus \
  && pandoc --version >/dev/null \
  && soffice --version >/dev/null \
  && printf '%%!PS\n/Helvetica findfont 24 scalefont setfont 72 700 moveto (check) show showpage\n' > /tmp/check.ps \
  && gs -q -dNOPAUSE -dBATCH -sDEVICE=pdfwrite -sOutputFile=/tmp/check.pdf /tmp/check.ps \
  && test -s /tmp/check.pdf \
  && pdftoppm -r 50 -png /tmp/check.pdf /tmp/check-page \
  && test -s /tmp/check-page-1.png \
  && rm -f /tmp/check.ps /tmp/check.pdf /tmp/check-page-1.png
RUN /opt/eggent-python/bin/python3 -c "import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt; \
plt.rcParams['font.family']='DejaVu Sans'; plt.figure(); plt.title('Проверка кириллицы'); \
plt.savefig('/tmp/check.png', dpi=50); import os; assert os.path.getsize('/tmp/check.png') > 1000" \
  && rm -f /tmp/check.png

# Всё, что сборка создала в /app/data от root, возвращается пользователю приложения.
RUN mkdir -p /app/data/.cache /app/data/tmp/matplotlib \
  && chown -R node:node /app/data/.cache /app/data/tmp

USER node
