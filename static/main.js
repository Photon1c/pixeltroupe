const socket = io();
const canvas = document.getElementById("world-canvas");
const ctx = canvas.getContext("2d");

const statusLine = document.getElementById("status-line");
const agentList = document.getElementById("agent-list");
const selectedAgentEl = document.getElementById("selected-agent");
const chatFeed = document.getElementById("chat-feed");
const messageInput = document.getElementById("agent-message");

const pauseBtn = document.getElementById("pause-btn");
const speedBtn = document.getElementById("speed-btn");
const trainBtn = document.getElementById("train-btn");
const spawnBtn = document.getElementById("spawn-btn");
const sendBtn = document.getElementById("send-btn");

let selectedAgentName = null;
let latestState = null;

function moodColor(mood) {
    switch ((mood || "").toLowerCase()) {
        case "happy":
            return "#ffd24a";
        case "grumpy":
            return "#c66b4b";
        default:
            return "#7d5fff";
    }
}

function tileSize(gridW, gridH) {
    const byWidth = Math.floor(canvas.width / gridW);
    const byHeight = Math.floor(canvas.height / gridH);
    return Math.max(12, Math.min(byWidth, byHeight));
}

function drawWorld(state) {
    if (!state) return;

    const gridW = state.grid_w || 24;
    const gridH = state.grid_h || 16;
    const tile = tileSize(gridW, gridH);
    const worldWidth = gridW * tile;
    const worldHeight = gridH * tile;

    ctx.fillStyle = "#11261e";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const originX = Math.floor((canvas.width - worldWidth) / 2);
    const originY = Math.floor((canvas.height - worldHeight) / 2);

    for (let y = 0; y < gridH; y += 1) {
        for (let x = 0; x < gridW; x += 1) {
            const shade = (x + y) % 2 === 0 ? "#2f7a4a" : "#2a7044";
            ctx.fillStyle = shade;
            ctx.fillRect(originX + x * tile, originY + y * tile, tile, tile);
        }
    }

    const agents = [...(state.agents || [])].sort((a, b) => a.y - b.y);
    agents.forEach((agent) => {
        const px = originX + agent.x * tile;
        const py = originY + agent.y * tile;

        ctx.fillStyle = moodColor(agent.mood);
        ctx.fillRect(px + 2, py + 2, tile - 4, tile - 4);

        if (selectedAgentName === agent.name) {
            ctx.strokeStyle = "#ffffff";
            ctx.lineWidth = 2;
            ctx.strokeRect(px + 1, py + 1, tile - 2, tile - 2);
        }

        ctx.fillStyle = "#111111";
        ctx.font = `${Math.max(10, Math.floor(tile * 0.5))}px monospace`;
        ctx.fillText((agent.name || "?")[0], px + tile * 0.28, py + tile * 0.7);

        if (agent.last_said) {
            const bubble = agent.last_said.slice(0, 24);
            const bubbleWidth = Math.max(68, bubble.length * 6 + 8);
            const bubbleX = px - 4;
            const bubbleY = py - 16;

            ctx.fillStyle = "rgba(0, 0, 0, 0.7)";
            ctx.fillRect(bubbleX, bubbleY - 12, bubbleWidth, 14);
            ctx.fillStyle = "#ffffff";
            ctx.font = "10px monospace";
            ctx.fillText(bubble, bubbleX + 4, bubbleY - 2);
        }
    });
}

function renderAgentList(state) {
    agentList.innerHTML = "";
    (state.agents || []).forEach((agent) => {
        const li = document.createElement("li");
        li.className = "agent-row";
        if (selectedAgentName === agent.name) {
            li.classList.add("selected");
        }
        li.textContent = `${agent.name} (${agent.mood}) r=${agent.total_reward}`;
        li.onclick = () => {
            selectedAgentName = agent.name;
            selectedAgentEl.textContent = `Selected: ${agent.name}`;
            renderAgentList(state);
            drawWorld(state);
        };
        agentList.appendChild(li);
    });
}

function renderChatFeed(state) {
    chatFeed.innerHTML = "";
    (state.chat_lines || []).forEach((line) => {
        const li = document.createElement("li");
        li.textContent = line;
        chatFeed.appendChild(li);
    });
}

function renderStatus(state) {
    const paused = state.paused ? "paused" : "running";
    statusLine.textContent = `${state.world_name} • tick ${state.tick} • ${paused} • speed ${state.speed_multiplier}x`;
}

function updateView(state) {
    latestState = state;
    drawWorld(state);
    renderAgentList(state);
    renderChatFeed(state);
    renderStatus(state);
}

async function postControl(action, value = null) {
    const payload = { action };
    if (value !== null) payload.value = value;
    const response = await fetch("/api/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (data.state) updateView(data.state);
}

pauseBtn.onclick = () => postControl("toggle_pause");
speedBtn.onclick = () => postControl("speed_x4");
trainBtn.onclick = () => postControl("train_now");
spawnBtn.onclick = () => postControl("spawn");

sendBtn.onclick = async () => {
    const message = messageInput.value.trim();
    if (!selectedAgentName || !message) return;
    await fetch(`/api/agent/${encodeURIComponent(selectedAgentName)}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
    });
    messageInput.value = "";
};

socket.on("connect", () => {
    statusLine.textContent = "Connected. Waiting for world updates...";
});

socket.on("world_update", (state) => {
    updateView(state);
});

fetch("/api/state")
    .then((response) => response.json())
    .then((state) => updateView(state))
    .catch(() => {
        statusLine.textContent = "Failed to load initial state.";
    });
