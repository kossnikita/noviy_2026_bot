// slot_wins.ts: Slot wins notification module for overlay
// Receives slot_win events via WebSocket and displays toast notifications

import { getUserName } from "./overlay_helpers";

export type SlotWin = {
    id: number;
    user_id: number;
    prize: {
        name: string;
        title: string;
    };
    won_at: string;
};

export type SlotWinNotification = {
    id: number;
    winnerName: string;
    prizeTitle: string;
    wonAt: Date;
};

// Queue of pending notifications
const notificationQueue: SlotWinNotification[] = [];
let isShowingNotification = false;

// Configuration
const NOTIFICATION_DISPLAY_MS = 5000;
const NOTIFICATION_ANIMATION_MS = 400;

// DOM elements (will be created dynamically)
let toastContainer: HTMLDivElement | null = null;
let toastElement: HTMLDivElement | null = null;

function createToastElements() {
    if (toastContainer) return;

    toastContainer = document.createElement("div");
    toastContainer.id = "slotWinToast";
    toastContainer.className = "slot-win-toast";
    toastContainer.innerHTML = `
        <div class="slot-win-toast__icon">🎰</div>
        <div class="slot-win-toast__content">
            <div class="slot-win-toast__title">Победа в слотах!</div>
            <div class="slot-win-toast__winner" id="slotWinWinner"></div>
            <div class="slot-win-toast__prize" id="slotWinPrize"></div>
        </div>
    `;
    document.body.appendChild(toastContainer);
    toastElement = toastContainer;
}

function showToast(notification: SlotWinNotification) {
    if (!toastElement) {
        createToastElements();
    }
    if (!toastElement) return;

    const winnerEl = toastElement.querySelector("#slotWinWinner") as HTMLDivElement;
    const prizeEl = toastElement.querySelector("#slotWinPrize") as HTMLDivElement;

    if (winnerEl) {
        winnerEl.textContent = `🏆 ${notification.winnerName}`;
    }
    if (prizeEl) {
        prizeEl.textContent = `Приз: ${notification.prizeTitle}`;
    }

    // Show animation
    toastElement.classList.remove("slot-win-toast--hidden");
    toastElement.classList.add("slot-win-toast--visible");

    console.log("overlay: showing slot win notification", {
        winner: notification.winnerName,
        prize: notification.prizeTitle,
    });
}

function hideToast() {
    if (!toastElement) return;
    toastElement.classList.remove("slot-win-toast--visible");
    toastElement.classList.add("slot-win-toast--hidden");
}

async function processNotificationQueue() {
    if (isShowingNotification || notificationQueue.length === 0) return;

    isShowingNotification = true;
    const notification = notificationQueue.shift()!;

    showToast(notification);

    // Wait for display duration
    await new Promise((resolve) => setTimeout(resolve, NOTIFICATION_DISPLAY_MS));

    hideToast();

    // Wait for hide animation
    await new Promise((resolve) => setTimeout(resolve, NOTIFICATION_ANIMATION_MS));

    isShowingNotification = false;

    // Process next notification if any
    if (notificationQueue.length > 0) {
        void processNotificationQueue();
    }
}

function queueNotification(notification: SlotWinNotification) {
    notificationQueue.push(notification);
    void processNotificationQueue();
}

/**
 * Handle incoming slot_win WebSocket message.
 * Call this from the main WS message handler when msg.type === "slot_win"
 */
export async function handleSlotWinMessage(
    msg: any,
    apiUrl: (p: string) => string,
    headers: () => HeadersInit
): Promise<void> {
    try {
        const win: SlotWin = {
            id: Number(msg.id || 0),
            user_id: Number(msg.user_id || 0),
            prize: {
                name: String(msg.prize?.name || ""),
                title: String(msg.prize?.title || "Unknown Prize"),
            },
            won_at: String(msg.won_at || ""),
        };

        if (!win.id || !win.user_id) {
            console.warn("overlay: invalid slot_win message", msg);
            return;
        }

        console.log("overlay: received slot_win via WS", win);

        // Resolve winner name
        const winnerName = await getUserName(
            String(win.user_id),
            apiUrl,
            headers
        );

        const notification: SlotWinNotification = {
            id: win.id,
            winnerName: winnerName || `User ${win.user_id}`,
            prizeTitle: win.prize.title,
            wonAt: new Date(win.won_at),
        };

        queueNotification(notification);
    } catch (err) {
        console.warn("overlay: failed to process slot_win message", err);
    }
}

/**
 * Initialize slot wins module.
 * Creates DOM elements for notifications.
 */
export function initSlotWins(): void {
    createToastElements();
    console.log("overlay: slot wins module initialized (WS mode)");
}
