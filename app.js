/* 
  app.js
  Interactive Logic & State Management for Grand Horizon Hotel System
*/

const STORAGE_KEY = "grand_horizon_hotel_rooms";

// Initial Room Data Structure matching Python backend
const DEFAULT_ROOMS = {
  "101": { type: "Standard", price: 50,  status: "Available", guest: null, nights: 0, services: 0 },
  "102": { type: "Standard", price: 50,  status: "Available", guest: null, nights: 0, services: 0 },
  "103": { type: "Deluxe",   price: 80,  status: "Available", guest: null, nights: 0, services: 0 },
  "201": { type: "Deluxe",   price: 80,  status: "Available", guest: null, nights: 0, services: 0 },
  "202": { type: "Suite",    price: 150, status: "Available", guest: null, nights: 0, services: 0 },
};

// Global App State
let rooms = loadRoomsData();
let activeFilter = "all";
let activeCheckoutRoom = null;

// Initialize App
document.addEventListener("DOMContentLoaded", () => {
  renderRooms();
  updateStats();
  setupEventListeners();
});

// Load rooms from localStorage or return defaults
function loadRoomsData() {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) {
    try {
      return JSON.parse(saved);
    } catch (e) {
      console.error("Error loading localStorage data", e);
    }
  }
  return JSON.parse(JSON.stringify(DEFAULT_ROOMS));
}

// Save rooms to localStorage
function saveRoomsData() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(rooms));
}

// Render Room Cards in Grid
function renderRooms() {
  const container = document.getElementById("rooms-container");
  container.innerHTML = "";

  Object.entries(rooms).forEach(([roomNum, info]) => {
    // Apply filter
    if (activeFilter === "available" && info.status !== "Available") return;
    if (activeFilter === "occupied" && info.status !== "Occupied") return;

    const isAvailable = info.status === "Available";
    const statusBadgeClass = isAvailable ? "badge-available" : "badge-occupied";
    const statusBadgeText = isAvailable ? "🟢 Available" : "🔴 Occupied";

    const card = document.createElement("div");
    card.className = "glass-card room-card";
    card.innerHTML = `
      <div class="room-header">
        <div>
          <div class="room-number">Room ${roomNum}</div>
          <span class="room-type">${info.type}</span>
        </div>
        <span class="status-badge ${statusBadgeClass}">${statusBadgeText}</span>
      </div>

      <div class="room-body">
        <div class="room-price">$${info.price} <span style="font-size: 0.85rem; color: var(--text-muted);">/ night</span></div>
        <div class="guest-info">
          Guest: <span>${info.guest ? info.guest : "None"}</span><br>
          Duration: <span>${info.nights > 0 ? info.nights + " night(s)" : "-"}</span>
        </div>
      </div>

      <div class="room-actions">
        ${isAvailable 
          ? `<button class="btn btn-primary" onclick="openCheckInModal('${roomNum}')">🛎️ Check-In</button>`
          : `<button class="btn btn-secondary" onclick="openCheckOutModal('${roomNum}')">🧾 Check-Out & Bill</button>`
        }
      </div>
    `;

    container.appendChild(card);
  });
}

// Update Dashboard Statistics
function updateStats() {
  const total = Object.keys(rooms).length;
  const occupied = Object.values(rooms).filter(r => r.status === "Occupied").length;
  const available = total - occupied;
  const revenue = Object.values(rooms)
    .filter(r => r.status === "Occupied")
    .reduce((sum, r) => sum + (r.price * r.nights) + (r.services || 0), 0);

  document.getElementById("stat-total").textContent = total;
  document.getElementById("stat-available").textContent = available;
  document.getElementById("stat-occupied").textContent = occupied;
  document.getElementById("stat-revenue").textContent = `$${revenue.toLocaleString()}`;
}

// Modal Control Helpers
function openModal(id) {
  document.getElementById(id).classList.add("active");
}

function closeModal(id) {
  document.getElementById(id).classList.remove("active");
}

// Open Check-In Modal
function openCheckInModal(preselectRoom = null) {
  const select = document.getElementById("select-room");
  select.innerHTML = "";

  const availableRooms = Object.entries(rooms).filter(([_, info]) => info.status === "Available");
  
  if (availableRooms.length === 0) {
    alert("Sorry! All rooms are currently occupied.");
    return;
  }

  availableRooms.forEach(([num, info]) => {
    const opt = document.createElement("option");
    opt.value = num;
    opt.textContent = `Room ${num} (${info.type} - $${info.price}/night)`;
    if (preselectRoom === num) opt.selected = true;
    select.appendChild(opt);
  });

  document.getElementById("guest-name").value = "";
  document.getElementById("stay-nights").value = "1";

  openModal("modal-checkin");
}

// Open Check-Out Invoice Modal
function openCheckOutModal(roomNum) {
  activeCheckoutRoom = roomNum;
  const info = rooms[roomNum];

  document.getElementById("invoice-guest").textContent = info.guest;
  document.getElementById("invoice-room").textContent = roomNum;
  document.getElementById("invoice-type").textContent = info.type;
  document.getElementById("invoice-rate").textContent = `$${info.price}`;
  document.getElementById("invoice-nights").textContent = info.nights;
  document.getElementById("addon-services").value = "0";

  recalculateInvoiceTotal();
  openModal("modal-checkout");
}

// Recalculate Checkout Invoice Total
function recalculateInvoiceTotal() {
  if (!activeCheckoutRoom) return;
  const info = rooms[activeCheckoutRoom];
  const roomCharge = info.price * info.nights;
  const addons = parseFloat(document.getElementById("addon-services").value) || 0;
  const total = roomCharge + addons;

  document.getElementById("invoice-services").textContent = `$${addons.toFixed(2)}`;
  document.getElementById("invoice-total").textContent = `$${total.toFixed(2)}`;
}

// Setup Event Listeners
function setupEventListeners() {
  // Top quick checkin button
  document.getElementById("btn-quick-checkin").addEventListener("click", () => openCheckInModal());

  // Check-in form submit
  document.getElementById("form-checkin").addEventListener("submit", (e) => {
    e.preventDefault();
    const roomNum = document.getElementById("select-room").value;
    const guestName = document.getElementById("guest-name").value.trim();
    const nights = parseInt(document.getElementById("stay-nights").value);

    if (!roomNum || !guestName || nights < 1) return;

    rooms[roomNum].status = "Occupied";
    rooms[roomNum].guest = guestName;
    rooms[roomNum].nights = nights;
    rooms[roomNum].services = 0;

    saveRoomsData();
    renderRooms();
    updateStats();
    closeModal("modal-checkin");
  });

  // Addon services input listener
  document.getElementById("addon-services").addEventListener("input", recalculateInvoiceTotal);

  // Confirm Check-out button
  document.getElementById("btn-confirm-checkout").addEventListener("click", () => {
    if (!activeCheckoutRoom) return;
    
    rooms[activeCheckoutRoom].status = "Available";
    rooms[activeCheckoutRoom].guest = null;
    rooms[activeCheckoutRoom].nights = 0;
    rooms[activeCheckoutRoom].services = 0;

    saveRoomsData();
    renderRooms();
    updateStats();
    closeModal("modal-checkout");
  });

  // Filter Buttons
  document.getElementById("filter-all").addEventListener("click", () => setFilter("all"));
  document.getElementById("filter-available").addEventListener("click", () => setFilter("available"));
  document.getElementById("filter-occupied").addEventListener("click", () => setFilter("occupied"));
}

function setFilter(filter) {
  activeFilter = filter;
  ["filter-all", "filter-available", "filter-occupied"].forEach(id => {
    const btn = document.getElementById(id);
    if (id === `filter-${filter}`) {
      btn.style.background = "var(--primary)";
      btn.style.color = "white";
    } else {
      btn.style.background = "rgba(255, 255, 255, 0.08)";
      btn.style.color = "var(--text-main)";
    }
  });
  renderRooms();
}
