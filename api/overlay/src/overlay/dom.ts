// DOM element references and helpers for overlay

export const el = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

export const titleEl = el<HTMLDivElement>("title");
export const artistsEl = el<HTMLDivElement>("artists");
export const albumEl = el<HTMLDivElement>("album");
export const requestedByEl = el<HTMLDivElement>("requestedBy");
export const coverImg = el<HTMLImageElement>("coverImg");
export const statusEl = el<HTMLDivElement>("status");
export const trackLayer = el<HTMLDivElement>("trackLayer"); export const photoLayer = el<HTMLDivElement>("photoLayer");
export const photoImg = el<HTMLImageElement>("photoImg");
export const photoCaption = el<HTMLDivElement>("photoCaption");
