// Audio element and playback helpers

export const audioEl = (() => {
    try {
        const a = document.createElement("audio");
        a.id = "noviy-audio";
        a.preload = "auto";
        a.style.display = "none";
        a.crossOrigin = "anonymous";
        document.body.appendChild(a);
        a.addEventListener("play", () => console.log("overlay: audio play event"));
        a.addEventListener("pause", () => console.log("overlay: audio pause event"));
        a.addEventListener("error", (e) => console.error("overlay: audio error", e));
        return a;
    } catch (e) {
        console.warn("overlay: failed to create audio element", e);
        return null as unknown as HTMLAudioElement;
    }
})();

export async function playAudioSrc(src: string) {
    if (!audioEl) return;
    try {
        if (audioEl.src !== src) {
            audioEl.src = src;
            audioEl.load();
        }
        await audioEl.play();
        console.log("overlay: playing audio src", src);
    } catch (e) {
        console.warn("overlay: audio play failed", e);
        throw e;
    }
}

export function pauseAudio() {
    if (!audioEl) return;
    try {
        audioEl.pause();
        console.log("overlay: audio paused");
    } catch (e) {
        console.warn("overlay: audio pause failed", e);
    }
}
