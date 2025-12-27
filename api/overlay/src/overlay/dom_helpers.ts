// Вспомогательные функции для работы с DOM

export function applyAnimation(img: HTMLImageElement) {
    img.classList.remove("anim-kenburns");
    img.classList.add("anim-kenburns");
}

export function safeSetImage(img: HTMLImageElement, src: string) {
    const s = (src || "").trim();
    if (!s) {
        img.removeAttribute("src");
        return;
    }
    if (img.src === s) return;
    img.decoding = "async";
    img.loading = "eager";
    img.src = s;
}
