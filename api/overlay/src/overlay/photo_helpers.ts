// photo_helpers.ts: функции для отображения фото в overlay
import { photoImg, photoCaption, photoLayer } from "./dom";
import { applyAnimation, safeSetImage } from "./dom_helpers";

let photoHideTimer: number | null = null;
export let lastPhotoId = 0;

export function showPhoto(url: string, caption: string) {
    safeSetImage(photoImg, url);
    applyAnimation(photoImg);
    photoCaption.textContent = caption;
    photoLayer.classList.remove("isHidden");
    if (photoHideTimer) window.clearTimeout(photoHideTimer);
    photoHideTimer = window.setTimeout(() => {
        photoLayer.classList.add("isHidden");
    }, 10000); // default, can be parameterized
}
