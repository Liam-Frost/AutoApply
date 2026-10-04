FROM greyltc/archlinux-aur

ENV TZ=Europe/Madrid \
    DISPLAY=:0 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/root/.local/bin:/root/.cargo/bin:${PATH}"

RUN pacman -Syu --noconfirm --needed \
    bash \
    ca-certificates \
    curl \
    git \
    wget \
    python \
    uv \
    tigervnc \
    i3-wm \
    i3status \
    chromium \
    xorg-xdpyinfo \
    xorg-xsetroot \
    ttf-dejavu \
    fontconfig \
    dbus \
    libreoffice-fresh \
    && pacman -Scc --noconfirm

COPY scripts/ /scripts/
RUN chmod +x /scripts/*.sh && /scripts/init.sh

WORKDIR /app

EXPOSE 6080

CMD ["/scripts/start.sh"]
