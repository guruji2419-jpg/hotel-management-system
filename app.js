/*
  app.js
  Grand Horizon Hotel & Resorts — Master Luxury Application Controller
  =====================================================================
  Crafted for ultra-premium digital hospitality management.
  Features:
  - Persistent Session Validation & Role-Based Access Control (RBAC)
  - Live Auto-Polling (15s) & Manual Instant Sync for Real-Time Multi-Client Consistency
  - Standardized Error Handling, Loading Skeletons, and Empty States
  - Dashboard: 7 Bespoke KPIs, Interactive Room Visualization, Active Stays
  - Guided 4-Step Check-In Wizard & Guided Check-Out Billing Workflow
  - Guest Portfolio Drawer with 4-tab history (Profile, Stays, Payments, Notes)
  - Room Dossier Drawer with instant status updates & amenities
  - Overlap-Checked Reservations & Dual View (List + Schedule Timeline)
  - 5-Column Housekeeping Kanban Board (Dirty, Cleaning, Clean, Inspected, Maint)
  - Reports & Analytics with Dark Gold Canvas Visualizations
  - Printable Luxury Hotel Folio Invoices
  - Rich Glassmorphic Modals, Confirm Dialogs & Toast Notifications
*/

// ==========================================================================
// 1. APPLICATION STATE
// ==========================================================================
let currentUser = null;
let currentToken = localStorage.getItem("hms_auth_token") || "";
let allRooms = [];
let allBookings = [];
let allGuests = [];
let allServices = [];
let allHousekeeping = [];
let currentBookingView = "list"; // 'list' or 'calendar'
let currentDashRoomFilter = "ALL";
let livePollInterval = null;
let editingBookingId = null;
let editingRoomId = null;
let editingGuestId = null;

// ==========================================================================
// 1.1 GLOBAL FETCH INTERCEPTOR (401 & SESSION EXPIRY HANDLING)
// ==========================================================================
const _origFetch = window.fetch;
window.fetch = async function(...args) {
  const [resource] = args;
  const res = await _origFetch.apply(this, args);

  // If unauthorized on any authenticated API call, clear stale credentials and show login screen
  if (res.status === 401 && typeof resource === "string" && resource.startsWith("/api/") && !resource.includes("/api/auth/login")) {
    if (currentToken) {
      console.warn("Session token expired or rejected by server. Clearing stale session credentials.");
      currentToken = "";
      currentUser = null;
      localStorage.removeItem("hms_auth_token");
      showAuthScreen(true);
      showToast("warning", "Session Expired", "Your login session has expired. Please sign in again.");
    }
  }
  return res;
};

// ==========================================================================
// 2. INITIALIZATION
// ==========================================================================
document.addEventListener("DOMContentLoaded", () => {
  initClock();
  setupEventListeners();

  if (currentToken) {
    verifySession();
  } else {
    showAuthScreen(true);
  }

  // Start background live polling
  initAutoSync();
});

function initClock() {
  function update() {
    const now = new Date();
    const clockEl = document.getElementById("topbar-clock");
    const dateEl  = document.getElementById("topbar-date");
    const greetEl = document.getElementById("dash-greeting");

    if (clockEl) {
      clockEl.textContent = now.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
    }
    if (dateEl) {
      dateEl.textContent = now.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });
    }
    if (greetEl) {
      const hour = now.getHours();
      const timeGreet = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
      const name = currentUser ? currentUser.full_name.split(" ")[0] : "Colleague";
      greetEl.textContent = `${timeGreet}, ${name}`;
    }
  }
  update();
  setInterval(update, 1000);
}

// ==========================================================================
// 3. REAL-TIME DATA SYNCHRONIZATION & AUTO-POLL STRATEGY
// ==========================================================================

function initAutoSync() {
  if (livePollInterval) clearInterval(livePollInterval);
  livePollInterval = setInterval(async () => {
    // Only poll when authenticated and user is not in the middle of a modal dialog
    if (!currentToken || !currentUser) return;
    const activeModals = document.querySelectorAll(".modal-overlay.active, .drawer-overlay.active");
    if (activeModals.length > 0) return;

    try {
      await syncState(true);
    } catch (e) {
      // Background poll silently catches connection blips
    }
  }, 15000); // Poll every 15 seconds
}

async function triggerManualSync() {
  const icon = document.getElementById("sync-spin-icon");
  if (icon) icon.style.transform = "rotate(360deg)";

  try {
    await syncState(false);
    showToast("success", "Synchronized", "All hotel data synchronized directly from live database.");
  } catch (e) {
    showToast("error", "Sync Error", "Unable to refresh data. Please check connection.");
  } finally {
    setTimeout(() => {
      if (icon) icon.style.transform = "rotate(0deg)";
    }, 600);
  }
}

async function refreshBadgeCounts() {
  const role = currentUser?.role ? currentUser.role.toLowerCase() : "";
  if (role === "cleaner" || role === "housekeeping") return;
  try {
    const res = await fetch("/api/bookings", {
      headers: { "Authorization": `Bearer ${currentToken}` }
    });
    if (res.ok) {
      const data = await res.json();
      if (data.bookings) {
        allBookings = data.bookings;
        const countBadge = document.getElementById("badge-bookings-count");
        if (countBadge) countBadge.textContent = allBookings.length;
      }
    }
  } catch (e) {}
}

// ==========================================================================
// 4. AUTHENTICATION & RBAC
// ==========================================================================
function showAuthScreen(show) {
  const screen = document.getElementById("auth-screen");
  const app    = document.getElementById("app-wrapper");
  if (show) {
    screen.classList.remove("hidden");
    if (app) app.classList.remove("visible");
  } else {
    screen.classList.add("hidden");
    if (app) app.classList.add("visible");
  }
}

function fillLogin(u, p) {
  const uInput = document.getElementById("login-user");
  const pInput = document.getElementById("login-pass");
  if (uInput) uInput.value = u;
  if (pInput) pInput.value = p;
}

async function verifySession() {
  try {
    const res = await fetch("/api/auth/me", {
      headers: { "Authorization": `Bearer ${currentToken}` }
    });
    if (res.ok) {
      const data = await res.json();
      if (data.success && data.user) {
        currentUser = data.user;
        showAuthScreen(false);
        applyRBAC();
        await loadAllData();
        return;
      }
    }
  } catch (e) {
    console.warn("Session check error:", e);
  }
  // Clear stale session token to prevent infinite 403 / Access Denied loops
  currentToken = "";
  currentUser = null;
  localStorage.removeItem("hms_auth_token");
  showAuthScreen(true);
}

function applyRBAC() {
  if (!currentUser) return;

  const name = currentUser.full_name || "User";
  const role = currentUser.role || "Staff";
  const initial = name.charAt(0).toUpperCase();

  const el = document.getElementById("user-display-name");
  const roleEl = document.getElementById("user-role-badge");
  const sidebarAvatar = document.getElementById("sidebar-avatar");
  const topbarAvatar  = document.getElementById("topbar-avatar");
  const topbarName    = document.getElementById("topbar-user-name");

  if (el) el.textContent = name;
  if (roleEl) roleEl.textContent = role;
  if (sidebarAvatar) sidebarAvatar.textContent = initial;
  if (topbarAvatar) topbarAvatar.textContent = initial;
  if (topbarName) topbarName.textContent = name.split(" ")[0];

  // RBAC visibility
  const adminElements = document.querySelectorAll(".admin-only");
  adminElements.forEach(elem => {
    elem.style.display = (role === "Admin") ? "" : "none";
  });
}

async function handleLogout() {
  try {
    await fetch("/api/auth/logout", {
      method: "POST",
      headers: { "Authorization": `Bearer ${currentToken}` }
    });
  } catch (e) {}

  localStorage.removeItem("hms_auth_token");
  currentToken = "";
  currentUser = null;
  closeSidebar();
  showAuthScreen(true);
  showToast("info", "Signed Out", "You have been securely signed out.");
}

// ==========================================================================
// 5. VIEW NAVIGATION
// ==========================================================================
function switchView(viewName) {
  const views = document.querySelectorAll(".view-section");
  views.forEach(v => v.classList.remove("active"));

  const target = document.getElementById(`view-${viewName}`);
  if (target) target.classList.add("active");

  const navBtns = document.querySelectorAll(".sidebar-nav-list button");
  navBtns.forEach(btn => btn.classList.remove("active"));

  const activeBtn = document.getElementById(`nav-${viewName}`);
  if (activeBtn) activeBtn.classList.add("active");

  closeSidebar();

  // Refresh target view data
  if (viewName === "dashboard")    loadDashboard();
  if (viewName === "bookings")     loadBookings();
  if (viewName === "guests")       loadGuests();
  if (viewName === "rooms")        loadRooms();
  if (viewName === "checkin")      loadCheckinView();
  if (viewName === "services")     loadServices();
  if (viewName === "housekeeping") loadHousekeeping();
  if (viewName === "maintenance")  loadMaintenanceData();
  if (viewName === "reports")      loadReports();
  if (viewName === "users" && currentUser?.role === "Admin") loadUsers();
}

let _syncStatePromise = null;

async function syncState(isBackground = false) {
  if (_syncStatePromise) {
    return _syncStatePromise;
  }

  _syncStatePromise = (async () => {
    try {
      const role = currentUser?.role ? currentUser.role.toLowerCase() : "";
      const isCleaner = (role === "cleaner" || role === "housekeeping");

      const promises = [
        loadDashboard(isBackground),
        loadRooms(isBackground),
        loadHousekeeping(isBackground),
        loadServices(isBackground)
      ];

      if (typeof loadMaintenanceData === "function") {
        promises.push(loadMaintenanceData(isBackground));
      }

      if (!isCleaner) {
        promises.push(loadBookings(isBackground));
        promises.push(loadGuests("", isBackground));
      }

      await Promise.allSettled(promises);

      // Refresh dependent UI components that rely on combined state
      populateCheckInRooms();
      populateCheckOutRooms();
      refreshBadgeCounts();

      const activeSection = document.querySelector(".view-section.active");
      const viewName = activeSection ? activeSection.id.replace("view-", "") : "dashboard";
      if (viewName === "checkin") {
        await loadCheckinView();
      } else if (viewName === "reports") {
        loadReports();
      } else if (viewName === "maintenance" && typeof loadMaintenanceData === "function") {
        loadMaintenanceData();
      }
    } catch (err) {
      console.error("State synchronization error:", err);
    } finally {
      _syncStatePromise = null;
    }
  })();

  return _syncStatePromise;
}

async function loadAllData() {
  return await syncState(false);
}

function toggleSidebar() {
  const sidebar  = document.getElementById("sidebar");
  const backdrop = document.getElementById("sidebar-backdrop");
  sidebar?.classList.toggle("open");
  backdrop?.classList.toggle("active");
}

function closeSidebar() {
  const sidebar  = document.getElementById("sidebar");
  const backdrop = document.getElementById("sidebar-backdrop");
  sidebar?.classList.remove("open");
  backdrop?.classList.remove("active");
}

// ==========================================================================
// 6. DASHBOARD CONTROLLER
// ==========================================================================
async function loadDashboard(isBackground = false) {
  try {
    const res = await fetch("/api/dashboard", {
      headers: { "Authorization": `Bearer ${currentToken}` }
    });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const data = await res.json();
    if (data.success && data.stats) {
      const s = data.stats;
      setKPI("d-total",     s.total);
      setKPI("d-available", s.available);
      setKPI("d-occupied",  s.occupied);
      setKPI("d-reserved",  s.reserved || 0);
      setKPI("d-checkins",  (data.active_checkins || []).length);
      setKPI("d-cleaning",  s.cleaning);
      setKPI("d-revenue",   `$${Number(s.revenue || 0).toLocaleString()}`);
      
      const occEl = document.getElementById("d-occupancy-pct");
      if (occEl) occEl.textContent = `${s.occupancy_rate || 0}% Occupancy`;

      renderActiveStays(data.active_checkins || []);
    }

    // Also fetch rooms for interactive dashboard grid
    const rRes = await fetch("/api/rooms", {
      headers: { "Authorization": `Bearer ${currentToken}` }
    });
    if (rRes.ok) {
      const rData = await rRes.json();
      if (rData.success && rData.list) {
        allRooms = rData.list;
        renderDashRoomsGrid(allRooms);
        
        const featCount = document.getElementById("login-feat-rooms");
        if (featCount) featCount.textContent = `${allRooms.length}+`;
      }
    }
  } catch (e) {
    console.error("Dashboard error:", e);
    if (!isBackground) {
      showToast("error", "Dashboard Notice", "Unable to refresh live statistics. Please try syncing again.");
    }
  }
}

function setKPI(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function filterDashRooms(status) {
  currentDashRoomFilter = status;
  const pills = document.querySelectorAll("#dash-room-filters .filter-pill-btn");
  pills.forEach(p => p.classList.remove("active"));
  
  if (window.event && window.event.target) {
    window.event.target.classList.add("active");
  }

  const filtered = (status === "ALL")
    ? allRooms
    : allRooms.filter(r => r.status === status);

  renderDashRoomsGrid(filtered);
}

function renderDashRoomsGrid(rooms) {
  const grid = document.getElementById("dash-rooms-grid");
  if (!grid) return;
  grid.innerHTML = "";

  if (rooms.length === 0) {
    grid.innerHTML = `<div style="grid-column:1/-1;">
      ${renderEmptyState(
        `<svg viewBox="0 0 24 24"><path d="M7 13c1.66 0 3-1.34 3-3S8.66 7 7 7s-3 1.34-3 3 1.34 3 3 3zm12-6h-8v7H3V5H1v15h2v-3h18v3h2v-9c0-2.21-1.79-4-4-4z"/></svg>`,
        "No Suites Match Filter",
        `No property suites currently correspond to the "${currentDashRoomFilter}" filter status.`,
        `<button class="btn btn-secondary btn-sm" onclick="filterDashRooms('ALL')">View All Suites</button>`
      )}
    </div>`;
    return;
  }

  rooms.forEach(r => {
    const card = document.createElement("div");
    card.className = `room-lux-card status-${r.status}`;
    card.onclick = () => openRoomDrawer(r.room_number);
    card.innerHTML = `
      <div class="room-lux-header">
        <div>
          <div class="room-lux-num">Room ${r.room_number}</div>
          <div class="room-lux-type-tag">${r.room_type} · Floor ${r.floor}</div>
        </div>
        <div class="room-lux-price-tag">
          <div class="room-lux-price">$${r.price_per_night}</div>
          <div class="room-lux-per-night">/ night</div>
        </div>
      </div>
      <div class="room-lux-body">
        <div class="room-lux-specs">
          <span>👥 Up to ${r.capacity}</span>
          <span>🛏️ ${r.bed_type || "Double"}</span>
          <span>❄️ ${r.ac_type || "AC"}</span>
        </div>
        <div class="room-lux-amenities">${r.amenities || "WiFi, Smart TV, Mini-bar"}</div>
        ${r.guest ? `
          <div class="room-guest-pill">
            <svg viewBox="0 0 24 24"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>
            <span>${escapeHtml(r.guest)}</span>
          </div>
        ` : ""}
      </div>
      <div class="room-lux-footer">
        <span class="badge-lux badge-${r.status}">${r.status}</span>
        <span style="color:var(--gold);font-size:0.75rem;">View Dossier →</span>
      </div>
    `;
    grid.appendChild(card);
  });
}

function renderActiveStays(stays) {
  const tbody = document.getElementById("table-active-stays");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (stays.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7">
      ${renderEmptyState(
        `<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>`,
        "No Active Stays At Present",
        "All rooms are currently vacant or awaiting arrivals. Check in incoming guests to initiate active folio tracking.",
        `<button class="btn btn-primary btn-sm" onclick="startGuidedCheckIn()">🛎️ Check In A Guest</button>`
      )}
    </td></tr>`;
    return;
  }

  stays.forEach(b => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong style="color:var(--gold-light);font-size:0.82rem;">${b.booking_code || "—"}</strong></td>
      <td><strong>Room ${b.room_number}</strong></td>
      <td>
        <div style="font-weight:600;">${escapeHtml(b.guest_name)}</div>
      </td>
      <td>${formatDate(b.check_in_date)}</td>
      <td>${formatDate(b.check_out_date)}</td>
      <td><span class="badge-lux badge-Checked-in">Checked-In</span></td>
      <td>
        <button class="btn btn-secondary btn-sm" onclick="triggerCheckout('${b.room_number}')">
          Check-Out
        </button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

// ==========================================================================
// 7. RESERVATIONS CONTROLLER (LIST & TIMELINE)
// ==========================================================================
async function loadBookings(isBackground = false) {
  const tbody = document.getElementById("table-bookings");
  if (tbody && !isBackground) renderTableSkeleton(tbody, 7, 4);

  try {
    const res = await fetch("/api/bookings", {
      headers: { "Authorization": `Bearer ${currentToken}` }
    });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const data = await res.json();
    allBookings = data.bookings || [];
    
    const countBadge = document.getElementById("badge-bookings-count");
    if (countBadge) countBadge.textContent = allBookings.length;

    renderBookings(allBookings);
    if (currentBookingView === "calendar") {
      renderBookingCalendar(allBookings);
    }
  } catch (e) {
    console.error("Bookings load error:", e);
    if (tbody && !isBackground) {
      tbody.innerHTML = `<tr><td colspan="7">
        ${renderEmptyState(
          `<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>`,
          "Unable to Load Reservations",
          "There was a problem communicating with the database. Please try reloading.",
          `<button class="btn btn-secondary btn-sm" onclick="loadBookings()">🔄 Retry Loading</button>`
        )}
      </td></tr>`;
    }
  }
}

function renderBookings(bookings) {
  const tbody = document.getElementById("table-bookings");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (bookings.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7">
      ${renderEmptyState(
        `<svg viewBox="0 0 24 24"><path d="M19 3h-1V1h-2v2H8V1H6v2H5c-1.11 0-1.99.9-1.99 2L3 19c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H5V8h14v11z"/></svg>`,
        "No Reservations Found",
        "No booking records match the specified search or filter criteria.",
        `<button class="btn btn-primary btn-sm" onclick="openNewBookingModal()">+ Create New Reservation</button>`
      )}
    </td></tr>`;
    return;
  }

  bookings.forEach(b => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong style="font-family:'Cinzel',serif;color:var(--gold-light);font-size:0.85rem;">${b.booking_code}</strong></td>
      <td>
        <div style="font-weight:600;color:var(--text-pure);">${escapeHtml(b.guest_name)}</div>
        <div style="font-size:0.75rem;color:var(--text-muted);">${escapeHtml(b.guest_phone || "")}</div>
      </td>
      <td><strong>Room ${b.room_number}</strong> <span style="font-size:0.75rem;color:var(--text-dim);">(${b.room_type})</span></td>
      <td>${formatDate(b.check_in_date)} → ${formatDate(b.check_out_date)}</td>
      <td style="color:var(--gold-light);font-weight:600;">$${b.advance_payment}</td>
      <td><span class="badge-lux badge-${b.status}">${b.status}</span></td>
      <td>
        <div style="display:flex;gap:4px;">
          <button class="btn btn-secondary btn-sm" onclick="openEditBookingModal(${b.id})">Edit</button>
          <button class="btn btn-ghost btn-sm" onclick="cancelBooking(${b.id})">❌</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function setBookingViewMode(mode) {
  currentBookingView = mode;
  const listBtn = document.getElementById("btn-view-booking-list");
  const calBtn  = document.getElementById("btn-view-booking-cal");
  const listContainer = document.getElementById("booking-list-container");
  const calContainer  = document.getElementById("booking-calendar-container");

  if (mode === "list") {
    listBtn?.classList.add("active");
    calBtn?.classList.remove("active");
    if (listContainer) listContainer.style.display = "block";
    if (calContainer) calContainer.style.display  = "none";
    renderBookings(allBookings);
  } else {
    calBtn?.classList.add("active");
    listBtn?.classList.remove("active");
    if (listContainer) listContainer.style.display = "none";
    if (calContainer) calContainer.style.display  = "block";
    renderBookingCalendar(allBookings);
  }
}

function renderBookingCalendar(bookings) {
  const container = document.getElementById("calendar-timeline-grid");
  if (!container) return;

  container.innerHTML = `
    <div style="margin-bottom:16px;display:flex;align-items:center;justify-content:space-between;">
      <h4 style="color:var(--text-pure);">Reservation Schedule Timeline</h4>
      <div style="font-size:0.8rem;color:var(--text-muted);">Live Overview of All Bookings</div>
    </div>
    <div style="display:flex;flex-direction:column;gap:12px;">
      ${bookings.slice(0, 10).map(b => `
        <div style="background:var(--charcoal-2);border:1px solid var(--border-subtle);border-radius:var(--radius-md);padding:14px 18px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;">
          <div>
            <span style="color:var(--gold-light);font-family:'Cinzel',serif;font-weight:700;">${b.booking_code}</span>
            <span style="margin:0 8px;color:var(--border-subtle);">|</span>
            <strong style="color:var(--text-pure);">${escapeHtml(b.guest_name)}</strong>
            <span style="font-size:0.8rem;color:var(--text-muted);margin-left:6px;">— Room ${b.room_number} (${b.room_type})</span>
          </div>
          <div style="display:flex;align-items:center;gap:16px;">
            <div style="font-size:0.82rem;color:var(--text-main);">
              📅 <strong>${formatDate(b.check_in_date)}</strong> to <strong>${formatDate(b.check_out_date)}</strong>
            </div>
            <span class="badge-lux badge-${b.status}">${b.status}</span>
          </div>
        </div>
      `).join("")}
    </div>
  `;
}

function filterBookings() {
  const search = (document.getElementById("booking-search")?.value || "").toLowerCase();
  const status = document.getElementById("booking-filter-status")?.value || "";

  const filtered = allBookings.filter(b => {
    const matchStatus = !status || b.status === status;
    const matchSearch = !search ||
      b.booking_code.toLowerCase().includes(search) ||
      b.guest_name.toLowerCase().includes(search) ||
      b.room_number.toLowerCase().includes(search);
    return matchStatus && matchSearch;
  });

  renderBookings(filtered);
}

// ==========================================================================
// 8. GUEST DIRECTORY & TABBED PROFILE DRAWER
// ==========================================================================
async function loadGuests(query = "", isBackground = false) {
  const tbody = document.getElementById("table-guests");
  if (tbody && !isBackground) renderTableSkeleton(tbody, 6, 4);

  try {
    const res = await fetch(`/api/guests?q=${encodeURIComponent(query)}`, {
      headers: { "Authorization": `Bearer ${currentToken}` }
    });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const data = await res.json();
    allGuests = data.guests || [];
    if (tbody) tbody.innerHTML = "";

    if (allGuests.length === 0) {
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="6">
          ${renderEmptyState(
            `<svg viewBox="0 0 24 24"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3z"/></svg>`,
            "No Guest Profiles Registered",
            query ? `No guests match "${escapeHtml(query)}". Try clearing or adjusting search term.` : "Your hotel clientele directory is empty. Register incoming guests to maintain comprehensive profiles.",
            `<button class="btn btn-primary btn-sm" onclick="openAddGuestModal()">+ Register New Guest</button>`
          )}
        </td></tr>`;
      }
      return;
    }

    allGuests.forEach(g => {
      const tr = document.createElement("tr");
      tr.style.cursor = "pointer";
      tr.innerHTML = `
        <td><span style="color:var(--gold-light);font-size:0.78rem;">#G-${g.id}</span></td>
        <td>
          <div style="font-weight:600;color:var(--text-pure);">${escapeHtml(g.full_name)}</div>
          <div style="font-size:0.72rem;color:var(--text-muted);">${escapeHtml(g.nationality || "International")}</div>
        </td>
        <td>
          <div style="font-size:0.85rem;">${escapeHtml(g.phone)}</div>
          <div style="font-size:0.75rem;color:var(--text-muted);">${escapeHtml(g.email || "—")}</div>
        </td>
        <td>${g.city ? `${escapeHtml(g.city)}, ` : ""}${escapeHtml(g.country || "—")}</td>
        <td>
          <span style="font-size:0.78rem;background:var(--charcoal-3);padding:3px 8px;border-radius:4px;border:1px solid var(--border-subtle);color:var(--text-muted);">
            ${escapeHtml(g.id_proof_type || "ID")}: ${escapeHtml(g.id_proof_number || "Verified")}
          </span>
        </td>
        <td>
          <div style="display:flex;gap:6px;">
            <button class="btn btn-secondary btn-sm" onclick="event.stopPropagation(); openGuestDrawer(${g.id})">
              Portfolio
            </button>
            <button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); openEditGuestModal(${g.id})">
              Edit
            </button>
            <button class="btn btn-danger btn-sm" onclick="event.stopPropagation(); confirmDeleteGuest(${g.id})">
              Delete
            </button>
          </div>
        </td>
      `;
      tr.onclick = () => openGuestDrawer(g.id);
      if (tbody) tbody.appendChild(tr);
    });
  } catch (e) {
    console.error("Guests load error:", e);
    if (tbody && !isBackground) {
      tbody.innerHTML = `<tr><td colspan="6">
        ${renderEmptyState(
          `<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>`,
          "Unable to Load Guests",
          "There was a problem retrieving guest records from the server.",
          `<button class="btn btn-secondary btn-sm" onclick="loadGuests()">🔄 Retry Loading</button>`
        )}
      </td></tr>`;
    }
  }
}

async function openGuestDrawer(guestId) {
  try {
    const res = await fetch(`/api/guests/${guestId}`, {
      headers: { "Authorization": `Bearer ${currentToken}` }
    });
    const data = await res.json();
    if (!data.success || !data.guest) {
      showToast("error", "Error", "Guest portfolio could not be retrieved.");
      return;
    }

    const g = data.guest;
    const bookings = data.bookings || [];
    const payments = data.payments || [];

    const titleEl = document.getElementById("drawer-guest-name");
    if (titleEl) titleEl.textContent = g.full_name;

    const bodyEl = document.getElementById("drawer-guest-body");
    if (!bodyEl) return;

    bodyEl.innerHTML = `
      <!-- TAB 1: Profile -->
      <div class="drawer-tab-content active" id="gtab-profile">
        <div style="display:flex;align-items:center;gap:18px;margin-bottom:24px;">
          <div style="display:flex;align-items:center;gap:18px;">
            <div style="width:64px;height:64px;border-radius:var(--radius-md);background:var(--gold-gradient);color:var(--bg-black);display:flex;align-items:center;justify-content:center;font-size:1.6rem;font-weight:700;box-shadow:0 4px 20px rgba(201,168,76,0.35);">
              ${g.full_name.charAt(0).toUpperCase()}
            </div>
            <div>
              <h3 style="font-family:'Cinzel',serif;color:var(--text-pure);">${escapeHtml(g.full_name)}</h3>
              <p style="color:var(--gold-light);font-size:0.8rem;">ID: #G-${g.id} · ${escapeHtml(g.nationality || "Citizen")}</p>
            </div>
          </div>
          <button class="btn btn-secondary btn-sm" onclick="closeDrawer('drawer-guest'); openEditGuestModal(${g.id})">✏️ Edit Profile</button>
        </div>

        <div style="background:var(--charcoal-1);border:1px solid var(--border-subtle);border-radius:var(--radius-lg);padding:20px;margin-bottom:20px;">
          <div class="inv-section-title">Contact &amp; Identification</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;font-size:0.85rem;">
            <div><span style="color:var(--text-muted);">Phone:</span> <strong>${escapeHtml(g.phone)}</strong></div>
            <div><span style="color:var(--text-muted);">Email:</span> <strong>${escapeHtml(g.email || "—")}</strong></div>
            <div><span style="color:var(--text-muted);">ID Type:</span> <strong>${escapeHtml(g.id_proof_type || "Passport")}</strong></div>
            <div><span style="color:var(--text-muted);">ID Number:</span> <strong>${escapeHtml(g.id_proof_number || "—")}</strong></div>
            <div><span style="color:var(--text-muted);">Location:</span> <strong>${escapeHtml(g.city || "")}, ${escapeHtml(g.country || "—")}</strong></div>
            <div><span style="color:var(--text-muted);">Member Since:</span> <strong>${formatDate(g.created_at)}</strong></div>
          </div>
        </div>

        <div style="background:var(--charcoal-1);border:1px solid var(--border-subtle);border-radius:var(--radius-lg);padding:20px;">
          <div class="inv-section-title">Emergency Contact</div>
          <div style="font-size:0.85rem;">
            <div>Name: <strong>${escapeHtml(g.emergency_name || "Not specified")}</strong></div>
            <div>Phone: <strong>${escapeHtml(g.emergency_phone || "Not specified")}</strong></div>
          </div>
        </div>
      </div>

      <!-- TAB 2: Stay History -->
      <div class="drawer-tab-content" id="gtab-stays">
        <div class="inv-section-title" style="margin-bottom:12px;">Booking Records (${bookings.length})</div>
        ${bookings.length === 0 ? `<p style="color:var(--text-muted);">No stay history recorded.</p>` : `
          <div style="display:flex;flex-direction:column;gap:10px;">
            ${bookings.map(b => `
              <div style="background:var(--charcoal-1);border:1px solid var(--border-subtle);border-radius:var(--radius-md);padding:14px;display:flex;justify-content:space-between;align-items:center;">
                <div>
                  <div style="font-weight:700;color:var(--gold-light);font-family:'Cinzel',serif;">${b.booking_code}</div>
                  <div style="font-size:0.82rem;color:var(--text-pure);margin-top:2px;">Room ${b.room_number} (${b.room_type})</div>
                  <div style="font-size:0.75rem;color:var(--text-muted);">${formatDate(b.check_in_date)} to ${formatDate(b.check_out_date)}</div>
                </div>
                <span class="badge-lux badge-${b.status}">${b.status}</span>
              </div>
            `).join("")}
          </div>
        `}
      </div>

      <!-- TAB 3: Payments -->
      <div class="drawer-tab-content" id="gtab-payments">
        <div class="inv-section-title" style="margin-bottom:12px;">Payment Transactions</div>
        ${payments.length === 0 ? `<p style="color:var(--text-muted);">No payment transactions recorded yet.</p>` : `
          <div style="display:flex;flex-direction:column;gap:10px;">
            ${payments.map(p => `
              <div style="background:var(--charcoal-1);border:1px solid var(--border-subtle);border-radius:var(--radius-md);padding:14px;display:flex;justify-content:space-between;align-items:center;">
                <div>
                  <div style="font-weight:600;color:var(--text-pure);">${p.payment_method || "Payment"}</div>
                  <div style="font-size:0.75rem;color:var(--text-muted);">${formatDate(p.payment_date)}</div>
                </div>
                <div style="color:var(--gold-light);font-weight:700;font-size:1.1rem;">$${p.amount}</div>
              </div>
            `).join("")}
          </div>
        `}
      </div>

      <!-- TAB 4: Notes -->
      <div class="drawer-tab-content" id="gtab-notes">
        <div class="inv-section-title" style="margin-bottom:12px;">Guest Preferences &amp; Requests</div>
        <div style="background:var(--charcoal-1);border:1px solid var(--border-subtle);border-radius:var(--radius-lg);padding:18px;">
          <p style="color:var(--text-main);font-size:0.88rem;line-height:1.6;">
            ${escapeHtml(g.special_requests || g.notes || "No special dietary or accommodation preferences logged for this guest profile.")}
          </p>
        </div>
      </div>
    `;

    openDrawer("drawer-guest");
  } catch (e) {
    console.error("Guest drawer load error:", e);
  }
}

function switchDrawerTab(tab) {
  const btns = document.querySelectorAll(".drawer-tab-btn");
  btns.forEach(b => b.classList.remove("active"));
  if (window.event && window.event.target) {
    window.event.target.classList.add("active");
  }

  const tabs = document.querySelectorAll(".drawer-tab-content");
  tabs.forEach(t => t.classList.remove("active"));

  const target = document.getElementById(`gtab-${tab}`);
  if (target) target.classList.add("active");
}

function confirmDeleteGuest(id) {
  const guest = allGuests.find(g => String(g.id) === String(id));
  const name = guest ? guest.full_name : "this guest";
  showConfirm(
    "Delete Guest Profile",
    `Are you sure you want to delete the profile for "${name}"? This action cannot be undone.`,
    async () => {
      try {
        const res = await fetch(`/api/guests/${id}`, {
          method: "DELETE",
          headers: { "Authorization": `Bearer ${currentToken}` }
        });
        const data = await res.json();
        if (res.ok && data.success) {
          showToast("success", "Deleted", data.message || "Guest profile deleted.");
          await loadAllData();
        } else {
          showToast("error", "Failed", data.message || data.error || "Failed to delete guest.");
        }
      } catch (e) {
        showToast("error", "Error", "Failed to delete guest.");
      }
    }
  );
}

// ==========================================================================
// 9. ROOMS & ROOM DOSSIER DRAWER
// ==========================================================================
async function loadRooms(isBackground = false) {
  const grid = document.getElementById("rooms-directory-grid");
  if (!grid) return;

  try {
    const res = await fetch("/api/rooms", {
      headers: { "Authorization": `Bearer ${currentToken}` }
    });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const data = await res.json();
    if (data.success && data.list) {
      allRooms = data.list;
      renderRoomsGrid(allRooms);
    }
  } catch (e) {
    console.error("Rooms load error:", e);
    if (!isBackground) {
      grid.innerHTML = `<div style="grid-column:1/-1;">
        ${renderEmptyState(
          `<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>`,
          "Unable to Load Room Inventory",
          "Could not retrieve room details from the database.",
          `<button class="btn btn-secondary btn-sm" onclick="loadRooms()">🔄 Retry</button>`
        )}
      </div>`;
    }
  }
}

function renderRoomsGrid(rooms) {
  const grid = document.getElementById("rooms-directory-grid");
  if (!grid) return;
  grid.innerHTML = "";

  if (rooms.length === 0) {
    grid.innerHTML = `<div style="grid-column:1/-1;">
      ${renderEmptyState(
        `<svg viewBox="0 0 24 24"><path d="M7 13c1.66 0 3-1.34 3-3S8.66 7 7 7s-3 1.34-3 3 1.34 3 3 3zm12-6h-8v7H3V5H1v15h2v-3h18v3h2v-9c0-2.21-1.79-4-4-4z"/></svg>`,
        "No Matching Suites Found",
        "No rooms matched your selected filter criteria. Clear filters to inspect all inventory.",
        `<button class="btn btn-secondary btn-sm" onclick="document.getElementById('room-filter-status').value=''; document.getElementById('room-filter-type').value=''; document.getElementById('room-search').value=''; filterRooms();">Reset Filters</button>`
      )}
    </div>`;
    return;
  }

  rooms.forEach(r => {
    const card = document.createElement("div");
    card.className = `room-lux-card status-${r.status}`;
    card.onclick = () => openRoomDrawer(r.room_number);
    card.innerHTML = `
      <div class="room-lux-header">
        <div>
          <div class="room-lux-num">Room ${r.room_number}</div>
          <div class="room-lux-type-tag">${r.room_type} · Floor ${r.floor}</div>
        </div>
        <div class="room-lux-price-tag">
          <div class="room-lux-price">$${r.price_per_night}</div>
          <div class="room-lux-per-night">/ night</div>
        </div>
      </div>
      <div class="room-lux-body">
        <div class="room-lux-specs">
          <span>👥 Capacity: ${r.capacity}</span>
          <span>🛏️ ${r.bed_type || "Double"}</span>
          <span>❄️ ${r.ac_type || "AC"}</span>
        </div>
        <div class="room-lux-amenities">${r.amenities || "High-speed WiFi, Smart TV, Mini-bar"}</div>
        ${r.guest ? `
          <div class="room-guest-pill">
            <svg viewBox="0 0 24 24"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>
            <span>${escapeHtml(r.guest)}</span>
          </div>
        ` : ""}
      </div>
      <div class="room-lux-footer" style="display:flex; justify-content:space-between; width:100%;">
        <div>
          <span class="badge-lux badge-${r.status}">${r.status}</span>
          <span class="badge-lux badge-${r.housekeeping_status || 'Clean'}">🧹 ${r.housekeeping_status || 'Clean'}</span>
        </div>
        <div style="display:flex; gap:6px;">
          ${(currentUser && currentUser.role === 'Admin') ? `
          <button class="btn btn-primary btn-sm" style="padding:2px 8px; font-size:0.75rem;" onclick="event.stopPropagation(); openEditRoomModal(${r.id})">Edit</button>
          <button class="btn btn-danger btn-sm" style="padding:2px 8px; font-size:0.75rem;" onclick="event.stopPropagation(); deleteRoom(${r.id})">Delete</button>
          ` : ''}
        </div>
      </div>
    `;
    grid.appendChild(card);
  });
}

function filterRooms() {
  const status = document.getElementById("room-filter-status")?.value || "";
  const type   = document.getElementById("room-filter-type")?.value || "";
  const search = (document.getElementById("room-search")?.value || "").toLowerCase();

  const filtered = allRooms.filter(r => {
    const matchStatus = !status || r.status === status;
    const matchType   = !type || r.room_type === type;
    const matchSearch = !search ||
      r.room_number.toLowerCase().includes(search) ||
      (r.room_type || "").toLowerCase().includes(search) ||
      (r.amenities || "").toLowerCase().includes(search);
    return matchStatus && matchType && matchSearch;
  });

  renderRoomsGrid(filtered);
}

function openRoomDrawer(roomNum) {
  const room = allRooms.find(r => String(r.room_number) === String(roomNum));
  if (!room) return;

  const titleEl = document.getElementById("drawer-room-title");
  if (titleEl) titleEl.textContent = `Room ${room.room_number} — ${room.room_type}`;

  const bodyEl = document.getElementById("drawer-room-body");
  if (!bodyEl) return;

  bodyEl.innerHTML = `
    <div style="position:relative;border-radius:var(--radius-lg);overflow:hidden;margin-bottom:24px;border:1px solid var(--border-subtle);">
      <div style="height:180px;background:url('https://images.unsplash.com/photo-1618773928121-c32242e63f39?w=800&q=80&fit=crop') center/cover no-repeat;"></div>
      <div style="position:absolute;bottom:12px;left:12px;right:12px;display:flex;justify-content:space-between;align-items:center;">
        <span class="badge-lux badge-${room.status}">${room.status}</span>
        <span class="badge-lux badge-Available" style="font-weight:700;">$${room.price_per_night} / night</span>
      </div>
    </div>

    <div style="background:var(--charcoal-1);border:1px solid var(--border-subtle);border-radius:var(--radius-lg);padding:20px;margin-bottom:20px;">
      <div class="inv-section-title">Room Specifications</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:0.85rem;">
        <div>Floor Level: <strong>Floor ${room.floor}</strong></div>
        <div>Capacity: <strong>${room.capacity} Guests</strong></div>
        <div>Bed Configuration: <strong>${room.bed_type || "King"}</strong></div>
        <div>Climate: <strong>${room.ac_type || "AC"}</strong></div>
        <div>Sanitation: <strong>${room.housekeeping_status || "Clean"}</strong></div>
      </div>
      <div style="margin-top:14px;padding-top:14px;border-top:1px solid var(--border-subtle);font-size:0.85rem;">
        <div style="color:var(--text-muted);margin-bottom:4px;">Amenities Included:</div>
        <div style="color:var(--text-pure);">${escapeHtml(room.amenities || "High-Speed WiFi, Smart TV, Premium Robes, Balcony")}</div>
      </div>
    </div>

    ${room.guest ? `
      <div style="background:rgba(244,63,94,0.08);border:1px solid rgba(244,63,94,0.25);border-radius:var(--radius-lg);padding:20px;margin-bottom:20px;">
        <div class="inv-section-title" style="color:#FDA4AF;">Active Occupant</div>
        <div style="font-size:0.95rem;font-weight:600;color:var(--text-pure);">${escapeHtml(room.guest)}</div>
        <div style="margin-top:14px;">
          <button class="btn btn-secondary btn-sm" onclick="closeDrawer('drawer-room'); triggerCheckout('${room.room_number}')">
            Initiate Check-Out →
          </button>
        </div>
      </div>
    ` : `
      <div style="margin-bottom:20px;">
        <button class="btn btn-primary w-full" onclick="closeDrawer('drawer-room'); startCheckInForRoom('${room.room_number}')">
          🛎️ Check Guest Into Room ${room.room_number}
        </button>
      </div>
    `}

    <div style="background:var(--charcoal-1);border:1px solid var(--border-subtle);border-radius:var(--radius-lg);padding:20px;">
      <div class="inv-section-title">Fast Housekeeping Update</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;">
        <button class="btn btn-secondary btn-sm" onclick="updateHKQuick('${room.room_number}', 'Clean')">✅ Mark Clean</button>
        <button class="btn btn-secondary btn-sm" onclick="updateHKQuick('${room.room_number}', 'Cleaning')">🧹 Mark Cleaning</button>
        <button class="btn btn-secondary btn-sm" onclick="updateHKQuick('${room.room_number}', 'Dirty')">⚠️ Mark Dirty</button>
        <button class="btn btn-secondary btn-sm" onclick="updateHKQuick('${room.room_number}', 'Maintenance')">🔧 Maintenance</button>
      </div>
    </div>

    ${(currentUser && (currentUser.role === 'Admin' || currentUser.role === 'Manager')) ? `
      <div style="margin-top:16px;display:flex;gap:10px;">
        <button class="btn btn-secondary btn-sm flex-1" onclick="closeDrawer('drawer-room'); openEditRoomModal(${room.id})">✏️ Edit Room</button>
        ${currentUser.role === 'Admin' ? `<button class="btn btn-danger btn-sm flex-1" onclick="closeDrawer('drawer-room'); deleteRoom(${room.id})">🗑️ Delete Room</button>` : ''}
      </div>
    ` : ''}
  `;

  openDrawer("drawer-room");
}

async function updateHKQuick(roomNum, status) {
  try {
    const res = await fetch("/api/housekeeping", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${currentToken}`
      },
      body: JSON.stringify({
        room_number: roomNum,
        cleaning_status: status,
        assigned_staff: currentUser ? currentUser.full_name : "Housekeeping Supervisor"
      })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showToast("success", "Housekeeping Updated", data.message);
      closeDrawer("drawer-room");
      await loadAllData();
    } else {
      showToast("error", "Error", data.message || "Failed to update housekeeping status.");
    }
  } catch (e) {
    showToast("error", "Error", "Failed to update room housekeeping.");
  }
}

// ==========================================================================
// 10. GUIDED CHECK-IN / CHECK-OUT CONTROLLER
// ==========================================================================
function showCheckFlow(flow) {
  const btnIn  = document.getElementById("btn-flow-checkin");
  const btnOut = document.getElementById("btn-flow-checkout");
  const btnDir = document.getElementById("btn-flow-directory");

  const wrapIn  = document.getElementById("flow-checkin-wrap");
  const wrapOut = document.getElementById("flow-checkout-wrap");
  const wrapDir = document.getElementById("flow-directory-wrap");

  [btnIn, btnOut, btnDir].forEach(b => b?.classList.remove("active"));
  [wrapIn, wrapOut, wrapDir].forEach(w => { if (w) w.style.display = "none"; });

  if (flow === "checkin") {
    btnIn?.classList.add("active");
    if (wrapIn) wrapIn.style.display = "block";
    populateCheckInRooms();
  } else if (flow === "checkout") {
    btnOut?.classList.add("active");
    if (wrapOut) wrapOut.style.display = "block";
    populateCheckOutRooms();
  } else {
    btnDir?.classList.add("active");
    if (wrapDir) wrapDir.style.display = "block";
  }
}

function startGuidedCheckIn() {
  switchView("checkin");
  showCheckFlow("checkin");
}

function startGuidedCheckOut() {
  switchView("checkin");
  showCheckFlow("checkout");
}

function startCheckInForRoom(roomNum) {
  switchView("checkin");
  showCheckFlow("checkin");
  nextCheckInStep(1);
  setTimeout(() => {
    populateCheckInRooms();
    const sel = document.getElementById("wiz-ci-room");
    if (sel) sel.value = String(roomNum);
    const gInput = document.getElementById("wiz-ci-guest");
    if (gInput) gInput.focus();
    showToast("info", "Room Selected", `Room ${roomNum} pre-selected. Enter guest details to continue.`);
  }, 100);
}

function nextCheckInStep(stepNum) {
  const gName = document.getElementById("wiz-ci-guest")?.value.trim();
  const room  = document.getElementById("wiz-ci-room")?.value;
  const nights = document.getElementById("wiz-ci-nights")?.value;

  if (stepNum >= 2 && !gName) {
    showToast("warning", "Guest Required", "Please enter guest name.");
    return;
  }
  if (stepNum >= 3 && !room) {
    showToast("warning", "Room Required", "Please select an available room.");
    return;
  }
  if (stepNum >= 4) {
    const nightsNum = parseInt(nights) || 1;
    if (nightsNum < 1) {
      showToast("warning", "Stay Duration", "Number of nights must be at least 1.");
      return;
    }
  }

  // Update step nodes
  for (let i = 1; i <= 4; i++) {
    const node = document.getElementById(`ci-step-${i}`);
    const panel = document.getElementById(`ci-panel-${i}`);
    if (node) {
      node.classList.remove("active", "completed");
      if (i < stepNum) node.classList.add("completed");
      if (i === stepNum) node.classList.add("active");
    }
    if (panel) {
      panel.classList.toggle("active", i === stepNum);
    }
  }

  if (stepNum === 4) {
    const roomObj = allRooms.find(r => String(r.room_number) === String(room));
    const price = roomObj ? Number(roomObj.price_per_night) : 80;
    const nightsNum = parseInt(nights) || 1;
    const subtotal = price * nightsNum;
    const tax = subtotal * 0.12;
    const grandTotal = subtotal + tax;

    const sumEl = document.getElementById("wiz-ci-summary");
    if (sumEl) {
      sumEl.innerHTML = `
        <div class="inv-section-title">Verification Summary</div>
        <div style="font-size:0.9rem;display:grid;grid-template-columns:1fr 1fr;gap:10px;">
          <div>Guest: <strong>${escapeHtml(gName)}</strong></div>
          <div>Assigned: <strong>Room ${room} (${roomObj ? roomObj.room_type : "Standard"})</strong></div>
          <div>Stay Length: <strong>${nightsNum} Night(s)</strong></div>
          <div>Accommodation Rate: <strong>$${subtotal.toFixed(2)} ($${price.toFixed(2)}/nt)</strong></div>
          <div>Estimated Tax (12%): <strong>$${tax.toFixed(2)}</strong></div>
          <div>Estimated Grand Total: <strong style="color:var(--gold-light);font-size:1.05rem;">$${grandTotal.toFixed(2)}</strong></div>
        </div>
      `;
    }
  }
}

function populateCheckInRooms() {
  const sel = document.getElementById("wiz-ci-room");
  if (!sel) return;
  const currentVal = sel.value;
  sel.innerHTML = `<option value="">— Select Available Room —</option>`;
  allRooms.filter(r => r.status === "Available").forEach(r => {
    const opt = document.createElement("option");
    opt.value = r.room_number;
    opt.textContent = `Room ${r.room_number} — ${r.room_type} ($${r.price_per_night}/night, Floor ${r.floor})`;
    sel.appendChild(opt);
  });
  if (currentVal && Array.from(sel.options).some(o => o.value === currentVal)) {
    sel.value = currentVal;
  }
}

function populateCheckOutRooms() {
  const sel = document.getElementById("wiz-co-room");
  if (!sel) return;
  const currentVal = sel.value;
  sel.innerHTML = `<option value="">— Select Occupied Room —</option>`;
  allRooms.filter(r => r.status === "Occupied").forEach(r => {
    const opt = document.createElement("option");
    opt.value = r.room_number;
    opt.textContent = `Room ${r.room_number} — ${r.guest || "Active Guest"}`;
    sel.appendChild(opt);
  });
  if (currentVal && Array.from(sel.options).some(o => o.value === currentVal)) {
    sel.value = currentVal;
  }
}

function updateCheckOutPreview(roomNum) {
  const preview = document.getElementById("wiz-co-preview");
  if (!preview) return;

  const room = allRooms.find(r => String(r.room_number) === String(roomNum));
  const activeBooking = allBookings.find(b => String(b.room_number) === String(roomNum) && b.status === "Checked-in");
  
  if (!room || !activeBooking) {
    preview.innerHTML = `<p style="color:var(--text-muted);font-size:0.85rem;">Select an occupied room to preview calculation.</p>`;
    return;
  }

  const sVal = parseFloat(document.getElementById("wiz-co-services")?.value) || 0;
  
  let nights = 1;
  try {
    const cin = new Date(activeBooking.check_in_date + "T00:00:00");
    const today = new Date();
    today.setHours(0,0,0,0);
    const actualNights = Math.round((today - cin) / (1000 * 60 * 60 * 24));
    let schedNights = 1;
    if (activeBooking.check_out_date) {
      const coutSched = new Date(activeBooking.check_out_date + "T00:00:00");
      schedNights = Math.round((coutSched - cin) / (1000 * 60 * 60 * 24));
    }
    nights = Math.max(schedNights, actualNights);
    if (nights < 1) nights = 1;
  } catch (e) {
    nights = 1;
  }

  const roomPrice = Number(activeBooking.room_price || room.price_per_night) || Number(room.price_per_night);
  const roomCharge = roomPrice * nights;
  const subtotal = roomCharge + sVal;
  const tax = subtotal * 0.12;
  const discount = Number(activeBooking.discount) || 0;
  const advance = Number(activeBooking.advance_payment) || 0;
  const grandTotal = subtotal + tax - discount;
  const balanceDue = Math.max(0, grandTotal - advance);

  preview.innerHTML = `
    <div class="inv-section-title">Preliminary Folio Calculation</div>
    <div style="font-size:0.88rem;display:grid;grid-template-columns:1fr 1fr;gap:10px;">
      <div>Room: <strong>Room ${room.room_number} (${room.room_type})</strong></div>
      <div>Guest: <strong>${escapeHtml(room.guest || activeBooking.guest_name || "Guest")}</strong></div>
      <div>Stay Duration: <strong>${nights} Night(s)</strong></div>
      <div>Room Charge: <strong>$${roomCharge.toFixed(2)} (${nights} × $${roomPrice.toFixed(2)})</strong></div>
      <div>Services / Addons: <strong>$${sVal.toFixed(2)}</strong></div>
      <div>Subtotal: <strong>$${subtotal.toFixed(2)}</strong></div>
      <div>Tax (12%): <strong>$${tax.toFixed(2)}</strong></div>
      <div>Discount: <strong style="color:var(--status-occ);">-$${discount.toFixed(2)}</strong></div>
      <div>Total Folio: <strong>$${grandTotal.toFixed(2)}</strong></div>
      <div>Advance Paid: <strong style="color:var(--status-avail);">-$${advance.toFixed(2)}</strong></div>
      <div style="grid-column:span 2;padding-top:8px;border-top:1px solid var(--border-subtle);font-size:1.05rem;color:var(--gold-light);">
        Final Balance Due: <strong>$${balanceDue.toFixed(2)}</strong>
      </div>
    </div>
  `;
}

async function loadCheckinView() {
  const tbody = document.getElementById("table-checkin-directory");
  if (tbody) renderTableSkeleton(tbody, 7, 4);

  try {
    const res = await fetch("/api/dashboard", {
      headers: { "Authorization": `Bearer ${currentToken}` }
    });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const data = await res.json();
    const stays = data.active_checkins || [];
    tbody.innerHTML = "";

    if (stays.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7">
        ${renderEmptyState(
          `<svg viewBox="0 0 24 24"><path d="M12.65 10C11.83 7.67 9.61 6 7 6c-3.31 0-6 2.69-6 6s2.69 6 6 6c2.61 0 4.83-1.67 5.65-4H17v4h4v-4h2v-4H12.65z"/></svg>`,
          "No Active Stays Registered",
          "There are currently no active checked-in guest folios in the hotel directory.",
          `<button class="btn btn-primary btn-sm" onclick="showCheckFlow('checkin')">Launch Guided Check-In</button>`
        )}
      </td></tr>`;
      return;
    }

    stays.forEach(b => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>Room ${b.room_number}</strong></td>
        <td><span style="color:var(--text-muted);font-size:0.8rem;">${b.room_type || "Suite"}</span></td>
        <td><strong style="color:var(--text-pure);">${escapeHtml(b.guest_name)}</strong></td>
        <td>${formatDate(b.check_in_date)}</td>
        <td>${formatDate(b.check_out_date)}</td>
        <td><span class="badge-lux badge-Checked-in">Checked-In</span></td>
        <td>
          <button class="btn btn-secondary btn-sm" onclick="triggerCheckout('${b.room_number}')">
            Check-Out
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    console.error("Checkin view load error:", e);
  }
}

async function triggerCheckout(roomNum) {
  showConfirm(
    "Confirm Departure & Folio Settlement",
    `Are you sure you want to check out Room ${roomNum}? A final itemized invoice will be generated.`,
    async () => {
      try {
        const res = await fetch("/api/check-out", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${currentToken}`
          },
          body: JSON.stringify({ room_num: roomNum, services: 0.0 })
        });
        const data = await res.json();
        if (res.ok && data.success) {
          showToast("success", "Check-Out Complete", data.message);
          await loadAllData();
          if (data.invoice) {
            renderPrintableInvoice(data.invoice);
          }
        } else {
          showToast("error", "Check-Out Failed", data.message || "Failed to process check-out.");
        }
      } catch (e) {
        showToast("error", "Error", "Check-out request failed.");
      }
    }
  );
}

async function quickCheckInBooking(roomNum, guestName) {
  try {
    const res = await fetch("/api/check-in", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${currentToken}`
      },
      body: JSON.stringify({ room_num: roomNum, guest_name: guestName, nights: 1 })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showToast("success", "Guest Checked In", data.message);
      await loadAllData();
    } else {
      showToast("error", "Check-In Failed", data.message || "Failed to check in guest.");
    }
  } catch (e) {
    showToast("error", "Error", "Check-in request failed.");
  }
}

// ==========================================================================
// 11. BILLING, SERVICES & PRINTABLE INVOICE
// ==========================================================================
async function loadServices(isBackground = false) {
  const tbody = document.getElementById("table-services");
  if (tbody && !isBackground) renderTableSkeleton(tbody, 4, 4);

  try {
    const res = await fetch("/api/services", {
      headers: { "Authorization": `Bearer ${currentToken}` }
    });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const data = await res.json();
    allServices = data.services || [];
    if (tbody) tbody.innerHTML = "";

    if (allServices.length === 0) {
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="5">
          ${renderEmptyState(
            `<svg viewBox="0 0 24 24"><path d="M11 9H9V2H7v7H5V2H3v7c0 2.12 1.66 3.84 3.75 3.97V22h2.5v-9.03C11.34 12.84 13 11.12 13 9V2h-2v7zm5-3v8h2.5v8H21V2c-2.76 0-5 2.24-5 4z"/></svg>`,
            "No Hotel Services Catalogued",
            "Amenity items, room dining, and concierge charges will be listed here.",
            `<button class="btn btn-primary btn-sm" onclick="openAddServiceChargeModal()">+ Add Service Charge</button>`
          )}
        </td></tr>`;
      }
      return;
    }

    allServices.forEach(s => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><span style="color:var(--gold-light);font-size:0.78rem;">#S-${s.id}</span></td>
        <td><strong style="color:var(--text-pure);">${escapeHtml(s.service_name)}</strong></td>
        <td><span class="badge-lux badge-Available">${escapeHtml(s.category)}</span></td>
        <td style="color:var(--gold-light);font-weight:700;font-size:0.95rem;">$${Number(s.unit_price).toFixed(2)}</td>
        <td style="text-align:center;">
          <button class="btn btn-secondary btn-sm" style="color:var(--status-occ);border-color:rgba(224,98,84,0.3);padding:4px 10px;font-size:0.75rem;" onclick="deleteServiceItem(${s.id}, '${escapeHtml(s.service_name)}')">
            Delete
          </button>
        </td>
      `;
      if (tbody) tbody.appendChild(tr);
    });
  } catch (e) {
    console.error("Services error:", e);
    if (tbody && !isBackground) {
      tbody.innerHTML = `<tr><td colspan="5">
        ${renderEmptyState(
          `<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>`,
          "Unable to Load Services",
          "Could not retrieve services catalog from server.",
          `<button class="btn btn-secondary btn-sm" onclick="loadServices()">🔄 Retry</button>`
        )}
      </td></tr>`;
    }
  }
}

async function deleteServiceItem(serviceId, serviceName) {
  showConfirm(
    "Remove Service Offering",
    `Are you sure you want to delete "${serviceName}" from the services catalog?`,
    async () => {
      try {
        const res = await fetch(`/api/services/${serviceId}`, {
          method: "DELETE",
          headers: { "Authorization": `Bearer ${currentToken}` }
        });
        const data = await res.json();
        if (res.ok && data.success) {
          showToast("success", "Service Removed", data.message);
          await loadServices();
        } else {
          showToast("error", "Error", data.message || "Failed to delete service.");
        }
      } catch (e) {
        showToast("error", "Error", "Failed to delete service.");
      }
    }
  );
}

function renderPrintableInvoice(inv) {
  const modalContent = document.getElementById("invoice-modal-content");
  if (!modalContent) return;

  const roomCharge = Number(inv.room_charge || (inv.price_per_night * (inv.nights || 1)) || 0);
  const serviceCharge = Number(inv.services_charge || 0);
  const subtotal = Number(inv.subtotal || (roomCharge + serviceCharge));
  const tax = Number(inv.tax_amount || (subtotal * 0.12));
  const discount = Number(inv.discount || 0);
  const advancePaid = Number(inv.advance_paid || 0);
  const grandTotal = Number(inv.grand_total || (subtotal + tax - discount));
  const balanceDue = Number(inv.balance_due || 0);

  modalContent.innerHTML = `
    <div class="invoice-paper">
      <div class="inv-brand-header">
        <div>
          <div class="inv-brand-name">GRAND HORIZON</div>
          <div class="inv-brand-tag">Hotel &amp; Luxury Resorts</div>
          <div style="font-size:0.75rem;color:var(--text-muted);margin-top:6px;">77 Oceanfront Boulevard, Azure Bay</div>
        </div>
        <div class="inv-num-block">
          <div class="inv-num-val">${inv.invoice_number || "INV-FINAL"}</div>
          <div class="inv-date-val">Date: ${new Date().toLocaleDateString("en-US", { year:"numeric", month:"long", day:"numeric" })}</div>
        </div>
      </div>

      <div class="inv-details-grid">
        <div>
          <div class="inv-section-title">Billed To</div>
          <div style="font-size:1rem;font-weight:700;color:var(--text-pure);">${escapeHtml(inv.guest || "Guest")}</div>
          <div style="font-size:0.8rem;color:var(--text-muted);margin-top:2px;">Room: <strong>Room ${inv.room_num} (${inv.type || "Suite"})</strong></div>
        </div>
        <div>
          <div class="inv-section-title">Folio Summary</div>
          <div style="font-size:0.82rem;color:var(--text-muted);">Stay Duration: <strong>${inv.nights || 1} Night(s)</strong></div>
          <div style="font-size:0.82rem;color:var(--text-muted);">Rate: <strong>$${Number(inv.price_per_night || (roomCharge / (inv.nights || 1))).toFixed(2)} / night</strong></div>
        </div>
      </div>

      <table class="inv-table">
        <thead>
          <tr>
            <th>Description</th>
            <th style="text-align:center;">Qty / Nights</th>
            <th style="text-align:right;">Rate</th>
            <th style="text-align:right;">Amount</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Accommodation Charges (Room ${inv.room_num})</td>
            <td style="text-align:center;">${inv.nights || 1}</td>
            <td style="text-align:right;">$${Number(inv.price_per_night || (roomCharge / (inv.nights || 1))).toFixed(2)}</td>
            <td style="text-align:right;">$${roomCharge.toFixed(2)}</td>
          </tr>
          ${serviceCharge > 0 ? `
            <tr>
              <td>Room Services &amp; Amenities Addons</td>
              <td style="text-align:center;">1</td>
              <td style="text-align:right;">$${serviceCharge.toFixed(2)}</td>
              <td style="text-align:right;">$${serviceCharge.toFixed(2)}</td>
            </tr>
          ` : ""}
        </tbody>
      </table>

      <div class="inv-totals-box">
        <div class="inv-total-row"><span>Subtotal:</span> <strong>$${subtotal.toFixed(2)}</strong></div>
        <div class="inv-total-row"><span>Resort &amp; City Tax (12%):</span> <strong>$${tax.toFixed(2)}</strong></div>
        ${discount > 0 ? `<div class="inv-total-row"><span>Discount:</span> <strong style="color:var(--status-occ);">-$${discount.toFixed(2)}</strong></div>` : ""}
        <div class="inv-total-row grand"><span>Total Folio:</span> <strong>$${grandTotal.toFixed(2)}</strong></div>
        ${advancePaid > 0 ? `<div class="inv-total-row"><span>Advance Paid:</span> <strong style="color:var(--status-avail);">-$${advancePaid.toFixed(2)}</strong></div>` : ""}
        <div class="inv-total-row" style="font-size:1.02rem;color:var(--gold-light);border-top:1px solid var(--border-subtle);margin-top:6px;padding-top:6px;">
          <span>Settlement Status:</span> <strong>${balanceDue <= 0 ? "PAID IN FULL ($" + grandTotal.toFixed(2) + ")" : "Balance Due: $" + balanceDue.toFixed(2)}</strong>
        </div>
      </div>

      <div style="margin-top:30px;padding-top:16px;border-top:1px solid var(--border-subtle);font-size:0.75rem;color:var(--text-dim);text-align:center;">
        Thank you for staying at Grand Horizon Hotel &amp; Resorts. We look forward to welcoming you back.
      </div>
    </div>
  `;

  openModal("modal-invoice");
}

// ==========================================================================
// 12. HOUSEKEEPING KANBAN BOARD
// ==========================================================================
async function loadHousekeeping(isBackground = false) {
  const tbody = document.getElementById("table-housekeeping");
  if (tbody && !isBackground) renderTableSkeleton(tbody, 7, 4);

  try {
    const res = await fetch("/api/housekeeping", {
      headers: { "Authorization": `Bearer ${currentToken}` }
    });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const data = await res.json();
    if (data.success && data.housekeeping) {
      allHousekeeping = data.housekeeping;
      renderHKBoard(allHousekeeping);
      renderHKTable(allHousekeeping);
    }
  } catch (e) {
    console.error("Housekeeping error:", e);
    if (tbody && !isBackground) {
      tbody.innerHTML = `<tr><td colspan="7">
        ${renderEmptyState(
          `<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>`,
          "Unable to Load Housekeeping",
          "Could not retrieve housekeeping status from server.",
          `<button class="btn btn-secondary btn-sm" onclick="loadHousekeeping()">🔄 Retry</button>`
        )}
      </td></tr>`;
    }
  }
}

const HK_COLUMNS = [
  { status: "Dirty",       label: "Dirty (To Clean)", color: "var(--status-occ)" },
  { status: "Cleaning",    label: "Cleaning in Progress", color: "var(--status-clean)" },
  { status: "Clean",       label: "Cleaned", color: "var(--status-avail)" },
  { status: "Inspected",   label: "Inspected & Approved", color: "var(--status-inspect)" },
  { status: "Maintenance", label: "Maintenance", color: "var(--status-maint)" }
];

function renderHKBoard(rooms) {
  const board = document.getElementById("hk-board");
  if (!board) return;
  board.innerHTML = "";

  HK_COLUMNS.forEach(col => {
    const colRooms = rooms.filter(r => (r.housekeeping_status || "Clean") === col.status);
    const colEl = document.createElement("div");
    colEl.className = "hk-kanban-col";
    colEl.innerHTML = `
      <div class="hk-col-header" style="border-top:3px solid ${col.color};">
        <span>${col.label}</span>
        <span class="hk-col-count">${colRooms.length}</span>
      </div>
      <div class="hk-col-cards">
        ${colRooms.length === 0 ? `<div style="text-align:center;padding:24px;color:var(--text-dim);font-size:0.75rem;">No rooms in this stage</div>` : ""}
      </div>
    `;

    const cardsContainer = colEl.querySelector(".hk-col-cards");
    colRooms.forEach(r => {
      const card = document.createElement("div");
      card.className = "hk-task-card";
      card.onclick = () => openHKModal(r.room_number, r.housekeeping_status);
      card.innerHTML = `
        <div class="hk-task-top">
          <span class="hk-task-room">Room ${r.room_number}</span>
          <span class="badge-lux badge-${r.room_status}">${r.room_status || "—"}</span>
        </div>
        <div class="hk-task-meta">${r.room_type || "Standard"} · Floor ${r.floor || "1"}</div>
        <div class="hk-task-staff">
          <svg viewBox="0 0 24 24"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>
          <span>${escapeHtml(r.assigned_staff || "Housekeeping Staff")}</span>
        </div>
      `;
      cardsContainer.appendChild(card);
    });

    board.appendChild(colEl);
  });
}

function renderHKTable(rooms) {
  const tbody = document.getElementById("table-housekeeping");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (rooms.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7">
      ${renderEmptyState(
        `<svg viewBox="0 0 24 24"><path d="M21.95 5.005l-3.306-.004c-1.036 0-1.887.712-2.115 1.673L15.724 8H5c-1.103 0-2 .897-2 2v8c0 1.103.897 2 2 2h14c1.103 0 2-.897 2-2V9.018c0-.003.001-.006.001-.009l.949-4.004z"/></svg>`,
        "No Housekeeping Entries Found",
        "All rooms sanitation statuses are currently up to date.",
        ""
      )}
    </td></tr>`;
    return;
  }

  rooms.forEach(h => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>Room ${h.room_number}</strong></td>
      <td>${h.room_type || "Standard"}</td>
      <td>Floor ${h.floor || "1"}</td>
      <td><span class="badge-lux badge-${h.room_status}">${h.room_status || "Available"}</span></td>
      <td><span class="badge-lux badge-${h.housekeeping_status}">${h.housekeeping_status}</span></td>
      <td>${escapeHtml(h.assigned_staff || "Housekeeping")}</td>
      <td>
        <button class="btn btn-secondary btn-sm" onclick="openHKModal('${h.room_number}', '${h.housekeeping_status}')">
          Update
        </button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

// ==========================================================================
// 12B. ROOM MAINTENANCE MANAGEMENT
// ==========================================================================
let allMaintenanceLogs = [];

async function loadMaintenanceData(isBackground = false) {
  const tbody = document.getElementById("table-maintenance");
  if (tbody && !isBackground) renderTableSkeleton(tbody, 9, 3);

  const statusFilter = document.getElementById("maint-filter-status")?.value || "";

  try {
    let url = "/api/maintenance";
    if (statusFilter) url += `?status=${encodeURIComponent(statusFilter)}`;

    const res = await fetch(url, {
      headers: { "Authorization": `Bearer ${currentToken}` }
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json();
    if (data.success) {
      allMaintenanceLogs = data.maintenance_logs || [];
      renderMaintenanceTable(allMaintenanceLogs);
      updateMaintenanceStats(data.stats, allMaintenanceLogs);
    }
  } catch (e) {
    console.error("Maintenance error:", e);
    if (tbody && !isBackground) {
      tbody.innerHTML = `<tr><td colspan="9">
        ${renderEmptyState(
          `<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>`,
          "Unable to Load Maintenance Logs",
          "Could not retrieve maintenance records from server.",
          `<button class="btn btn-secondary btn-sm" onclick="loadMaintenanceData()">🔄 Retry</button>`
        )}
      </td></tr>`;
    }
  }
}

function updateMaintenanceStats(stats, logs) {
  const activeEl = document.getElementById("maint-stat-active");
  const urgentEl = document.getElementById("maint-stat-urgent");
  const resolvedEl = document.getElementById("maint-stat-resolved");
  const badgeEl = document.getElementById("badge-maintenance-count");

  const urgentCount = logs.filter(l => (l.priority === "Urgent" || l.priority === "High") && l.status !== "Resolved").length;

  if (activeEl) activeEl.textContent = stats?.active || 0;
  if (urgentEl) urgentEl.textContent = urgentCount;
  if (resolvedEl) resolvedEl.textContent = stats?.resolved || 0;

  if (badgeEl) {
    const count = stats?.active || 0;
    if (count > 0) {
      badgeEl.textContent = count;
      badgeEl.style.display = "inline-block";
    } else {
      badgeEl.style.display = "none";
    }
  }
}

function renderMaintenanceTable(logs) {
  const tbody = document.getElementById("table-maintenance");
  if (!tbody) return;

  if (!logs || logs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9">
      ${renderEmptyState(
        `<svg viewBox="0 0 24 24"><path d="M22.7 19l-9.1-9.1c.9-2.3.4-5-1.5-6.9-2-2-5-2.4-7.4-1.3L9 6 6 9 1.6 4.7C.4 7.1.9 10.1 2.9 12.1c1.9 1.9 4.6 2.4 6.9 1.5l9.1 9.1c.4.4 1 .4 1.4 0l2.4-2.4c.4-.4.4-1 0-1.3z"/></svg>`,
        "No Maintenance Work Orders",
        "There are no room maintenance records matching the selected status."
      )}
    </td></tr>`;
    return;
  }

  tbody.innerHTML = logs.map(l => {
    let priorityBadge = `<span class="badge" style="background:#3498db;color:#fff;">Low</span>`;
    if (l.priority === "Medium") priorityBadge = `<span class="badge" style="background:#f39c12;color:#fff;">Medium</span>`;
    if (l.priority === "High") priorityBadge = `<span class="badge" style="background:#e67e22;color:#fff;">High</span>`;
    if (l.priority === "Urgent") priorityBadge = `<span class="badge" style="background:#e74c3c;color:#fff;">Urgent</span>`;

    let statusBadge = `<span class="badge" style="background:#e74c3c;color:#fff;">Open</span>`;
    if (l.status === "In Progress") statusBadge = `<span class="badge" style="background:#f39c12;color:#fff;">In Progress</span>`;
    if (l.status === "Resolved") statusBadge = `<span class="badge" style="background:#2ecc71;color:#fff;">Resolved</span>`;

    let actionBtn = "";
    if (l.status === "Open") {
      actionBtn = `
        <button class="btn btn-secondary btn-sm" onclick="updateMaintenanceStatus(${l.id}, 'In Progress')">▶️ Start Work</button>
        <button class="btn btn-primary btn-sm" onclick="updateMaintenanceStatus(${l.id}, 'Resolved')">✅ Resolve</button>
      `;
    } else if (l.status === "In Progress") {
      actionBtn = `
        <button class="btn btn-primary btn-sm" onclick="updateMaintenanceStatus(${l.id}, 'Resolved')">✅ Resolve & Restore Room</button>
      `;
    } else {
      actionBtn = `<span style="color:var(--text-muted);font-size:0.8rem;">Resolved ${l.resolved_at ? l.resolved_at.split('T')[0] : ''}</span>`;
    }

    return `
      <tr>
        <td><strong>#${l.id}</strong></td>
        <td><strong style="color:var(--gold-400);">Room ${l.room_number}</strong></td>
        <td>${l.issue_category}</td>
        <td>${priorityBadge}</td>
        <td><div style="max-width:250px;white-space:normal;font-size:0.85rem;">${escapeHTML(l.description || 'N/A')}</div></td>
        <td>${escapeHTML(l.reported_by || 'Staff')}</td>
        <td>${escapeHTML(l.assigned_staff || 'Unassigned')}</td>
        <td>${statusBadge}</td>
        <td><div style="display:flex;gap:6px;">${actionBtn}</div></td>
      </tr>
    `;
  }).join("");
}

function openMaintenanceModal(prefillRoom = "") {
  const roomSelect = document.getElementById("maint-room-select");
  if (roomSelect && typeof allRooms !== 'undefined' && allRooms) {
    roomSelect.innerHTML = `<option value="">Select Room</option>` +
      allRooms.map(r => `<option value="${r.room_number}" ${r.room_number === prefillRoom ? 'selected' : ''}>Room ${r.room_number} (${r.room_type} - ${r.status})</option>`).join("");
  }
  document.getElementById("form-log-maintenance")?.reset();
  if (prefillRoom && roomSelect) roomSelect.value = prefillRoom;
  openModal("modal-maintenance");
}

async function handleLogMaintenance(e) {
  e.preventDefault();
  const roomNum = document.getElementById("maint-room-select")?.value;
  const category = document.getElementById("maint-category")?.value;
  const priority = document.getElementById("maint-priority")?.value;
  const assigned = document.getElementById("maint-assigned")?.value;
  const description = document.getElementById("maint-description")?.value;

  if (!roomNum || !category || !description) {
    showToast("error", "Required Fields", "Please select room, category and provide issue description.");
    return;
  }

  try {
    const res = await fetch("/api/maintenance", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${currentToken}`
      },
      body: JSON.stringify({
        room_number: roomNum,
        issue_category: category,
        priority: priority,
        assigned_staff: assigned,
        description: description
      })
    });

    const data = await res.json();
    if (data.success) {
      showToast("success", "Maintenance Logged", data.message || `Room ${roomNum} set to Maintenance.`);
      closeModal("modal-maintenance");
      loadMaintenanceData();
      loadRooms();
      loadHousekeeping();
      loadDashboard();
    } else {
      showToast("error", "Log Failed", data.message || "Could not log maintenance issue.");
    }
  } catch (err) {
    console.error(err);
    showToast("error", "Server Error", "An error occurred while logging maintenance.");
  }
}

async function updateMaintenanceStatus(id, status) {
  try {
    const res = await fetch("/api/maintenance", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${currentToken}`
      },
      body: JSON.stringify({ id, status })
    });

    const data = await res.json();
    if (data.success) {
      showToast("success", "Work Order Updated", data.message || `Maintenance status updated.`);
      loadMaintenanceData();
      loadRooms();
      loadHousekeeping();
      loadDashboard();
    } else {
      showToast("error", "Update Failed", data.message || "Could not update maintenance status.");
    }
  } catch (err) {
    console.error(err);
    showToast("error", "Server Error", "An error occurred while updating maintenance.");
  }
}

// ==========================================================================
// 13. REPORTS & ANALYTICS CANVAS VISUALIZATIONS
// ==========================================================================
async function loadReports() {
  try {
    const res = await fetch("/api/dashboard", {
      headers: { "Authorization": `Bearer ${currentToken}` }
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.success && data.stats) {
      const s = data.stats;
      const statsEl = document.getElementById("report-stats");
      if (statsEl) {
        statsEl.innerHTML = `
          <div class="kpi-card-lux kpi-gold">
            <div class="kpi-card-label">Total Rooms</div>
            <div class="kpi-main-val">${s.total}</div>
          </div>
          <div class="kpi-card-lux kpi-green">
            <div class="kpi-card-label">Available</div>
            <div class="kpi-main-val">${s.available}</div>
          </div>
          <div class="kpi-card-lux kpi-red">
            <div class="kpi-card-label">Occupied</div>
            <div class="kpi-main-val">${s.occupied}</div>
          </div>
          <div class="kpi-card-lux kpi-featured-revenue">
            <div class="kpi-card-label">Cumulative Revenue</div>
            <div class="kpi-main-val">$${Number(s.revenue || 0).toLocaleString()}</div>
          </div>
        `;
      }

      renderReportsCharts(s);
    }
  } catch (e) {
    console.error("Reports error:", e);
  }
}

function renderReportsCharts(stats) {
  // 1. Revenue Chart (Canvas line & bar simulation in Dark Gold)
  const revCanvas = document.getElementById("chart-revenue");
  if (revCanvas) {
    const ctx = revCanvas.getContext("2d");
    revCanvas.width = revCanvas.parentElement.clientWidth || 500;
    revCanvas.height = 240;

    const w = revCanvas.width;
    const h = revCanvas.height;
    ctx.clearRect(0, 0, w, h);

    // Draw background grid lines
    ctx.strokeStyle = "rgba(255, 255, 255, 0.05)";
    ctx.lineWidth = 1;
    for (let y = 30; y < h; y += 40) {
      ctx.beginPath();
      ctx.moveTo(30, y);
      ctx.lineTo(w - 20, y);
      ctx.stroke();
    }

    // Gradient area
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, "rgba(201, 168, 76, 0.35)");
    grad.addColorStop(1, "rgba(201, 168, 76, 0.0)");

    const points = [
      { x: 40, y: h - 50 },
      { x: w * 0.22, y: h - 85 },
      { x: w * 0.40, y: h - 70 },
      { x: w * 0.58, y: h - 130 },
      { x: w * 0.75, y: h - 110 },
      { x: w - 30, y: h - 180 }
    ];

    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    for (let i = 1; i < points.length; i++) {
      ctx.lineTo(points[i].x, points[i].y);
    }
    ctx.lineTo(points[points.length - 1].x, h - 20);
    ctx.lineTo(points[0].x, h - 20);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // Stroke line
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    for (let i = 1; i < points.length; i++) {
      ctx.lineTo(points[i].x, points[i].y);
    }
    ctx.strokeStyle = "#C9A84C";
    ctx.lineWidth = 3;
    ctx.shadowColor = "rgba(201, 168, 76, 0.6)";
    ctx.shadowBlur = 12;
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Data points
    points.forEach(p => {
      ctx.beginPath();
      ctx.arc(p.x, p.y, 5, 0, Math.PI * 2);
      ctx.fillStyle = "#EBD59B";
      ctx.fill();
      ctx.strokeStyle = "#070709";
      ctx.lineWidth = 2;
      ctx.stroke();
    });
  }

  // 2. Occupancy Donut Chart
  const occCanvas = document.getElementById("chart-occupancy");
  if (occCanvas) {
    const ctx = occCanvas.getContext("2d");
    occCanvas.width = occCanvas.parentElement.clientWidth || 260;
    occCanvas.height = 240;

    const cx = occCanvas.width / 2;
    const cy = occCanvas.height / 2;
    const r  = 75;
    ctx.clearRect(0, 0, occCanvas.width, occCanvas.height);

    const total = stats.total || 5;
    const avail = stats.available || 2;
    const occ   = stats.occupied || 2;
    const clean = stats.cleaning || 1;

    const slices = [
      { val: avail, color: "#10B981" },
      { val: occ,   color: "#F43F5E" },
      { val: clean, color: "#38BDF8" }
    ];

    let start = -Math.PI / 2;
    slices.forEach(s => {
      const sliceAngle = (s.val / total) * Math.PI * 2;
      ctx.beginPath();
      ctx.arc(cx, cy, r, start, start + sliceAngle);
      ctx.arc(cx, cy, r - 26, start + sliceAngle, start, true);
      ctx.closePath();
      ctx.fillStyle = s.color;
      ctx.shadowColor = s.color;
      ctx.shadowBlur = 8;
      ctx.fill();
      ctx.shadowBlur = 0;
      start += sliceAngle;
    });

    // Center rate
    ctx.fillStyle = "#F7F3EB";
    ctx.font = "bold 20px 'Cinzel', serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(`${stats.occupancy_rate || 0}%`, cx, cy);
  }
}

function downloadCSV(type) {
  window.open(`/api/reports/export/csv?type=${type}&token=${currentToken}`, "_blank");
}

// ==========================================================================
// 14. STAFF & USERS CONTROLLER
// ==========================================================================
async function loadUsers() {
  const tbody = document.getElementById("table-users");
  if (tbody) renderTableSkeleton(tbody, 5, 3);

  try {
    const res = await fetch("/api/auth/users", {
      headers: { "Authorization": `Bearer ${currentToken}` }
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    tbody.innerHTML = "";

    if (!data.success || !data.users || data.users.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5">
        ${renderEmptyState(
          `<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg>`,
          "No Staff Accounts",
          "No employee records registered in the system.",
          `<button class="btn btn-primary btn-sm" onclick="openAddUserModal()">+ Add Staff Account</button>`
        )}
      </td></tr>`;
      return;
    }

    data.users.forEach(u => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><span style="color:var(--gold-light);font-size:0.78rem;">#U-${u.id}</span></td>
        <td><strong style="color:var(--text-pure);">${escapeHtml(u.username)}</strong></td>
        <td>${escapeHtml(u.full_name)}</td>
        <td><span class="badge-lux badge-Available">${escapeHtml(u.role)}</span></td>
        <td style="font-size:0.8rem;color:var(--text-muted);">${formatDate(u.created_at)}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    console.error("Users load error:", e);
  }
}

// ==========================================================================
// 15. MODAL & DRAWER CONTROLS
// ==========================================================================
function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add("active");
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove("active");
  if (id === "modal-room") editingRoomId = null;
  if (id === "modal-guest") editingGuestId = null;
  if (id === "modal-booking") editingBookingId = null;
}

function openDrawer(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add("active");
}

function closeDrawer(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove("active");
}

// Close on backdrop click
document.addEventListener("click", (e) => {
  if (e.target.classList.contains("modal-overlay")) {
    e.target.classList.remove("active");
  }
  if (e.target.classList.contains("drawer-overlay")) {
    e.target.classList.remove("active");
  }
});

function openAddGuestModal() {
  editingGuestId = null;
  document.getElementById("form-guest")?.reset();
  const title = document.querySelector("#modal-guest h3");
  if (title) title.textContent = "Register Guest Profile";
  const btn = document.querySelector("#modal-guest button[type=submit]");
  if (btn) btn.textContent = "Create Profile";
  openModal("modal-guest");
}

function openEditGuestModal(guestId) {
  const guest = allGuests.find(g => String(g.id) === String(guestId));
  if (!guest) return;
  
  editingGuestId = guestId;
  document.getElementById("form-guest")?.reset();
  
  const title = document.querySelector("#modal-guest h3");
  if (title) title.textContent = "Edit Guest Profile";
  const btn = document.querySelector("#modal-guest button[type=submit]");
  if (btn) btn.textContent = "Save Changes";
  
  const gName = document.getElementById("g-name");
  const gPhone = document.getElementById("g-phone");
  const gEmail = document.getElementById("g-email");
  const gCity = document.getElementById("g-city");
  const gIdtype = document.getElementById("g-idtype");
  const gIdnum = document.getElementById("g-idnum");
  
  if (gName) gName.value = guest.full_name || "";
  if (gPhone) gPhone.value = guest.phone || "";
  if (gEmail) gEmail.value = guest.email || "";
  if (gCity) gCity.value = guest.city || "";
  if (gIdtype) gIdtype.value = guest.id_proof_type || "";
  if (gIdnum) gIdnum.value = guest.id_proof_number || "";
  
  openModal("modal-guest");
}

window.calculateBooking = function() {
  const checkIn = document.getElementById("b-in")?.value;
  const checkOut = document.getElementById("b-out")?.value;
  const roomSelect = document.getElementById("b-room");
  const advance = parseFloat(document.getElementById("b-advance")?.value) || 0;
  const discount = parseFloat(document.getElementById("b-discount")?.value) || 0;

  if (checkIn && checkOut && roomSelect) {
    const cin = new Date(checkIn);
    const cout = new Date(checkOut);
    const diffTime = cout - cin;
    let nights = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    if (nights < 1 || isNaN(nights)) nights = 0;
    
    // Filter rooms based on overlap
    const currentSelectedRoom = roomSelect.value;
    roomSelect.innerHTML = `<option value="">— Select Luxury Room —</option>`;
    
    allRooms.forEach(r => {
      if (r.status === "Maintenance") return;
      
      const overlap = allBookings.some(b => {
        if (String(b.room_id) !== String(r.id)) return false;
        if (b.status !== "Confirmed" && b.status !== "Checked-in") return false;
        if (editingBookingId && String(b.id) === String(editingBookingId)) return false;
        
        const bIn = new Date(b.check_in_date);
        const bOut = new Date(b.check_out_date);
        return !(bOut <= cin || bIn >= cout);
      });
      
      let isBlockedForToday = false;
      const today = new Date();
      today.setHours(0,0,0,0);
      if (cin.getTime() === today.getTime() && r.status === "Cleaning") {
          isBlockedForToday = true;
      }
      
      if (!overlap && !isBlockedForToday) {
        const opt = document.createElement("option");
        opt.value = r.id;
        opt.textContent = `Room ${r.room_number} — ${r.room_type} ($${r.price_per_night}/night)`;
        roomSelect.appendChild(opt);
      }
    });
    
    if (currentSelectedRoom) {
      roomSelect.value = currentSelectedRoom;
    }

    document.getElementById("b-nights").textContent = nights;
    
    if (nights > 0 && roomSelect.value) {
      const roomId = parseInt(roomSelect.value, 10);
      const room = allRooms.find(r => r.id === roomId);
      if (room) {
        const subtotal = room.price_per_night * nights;
        const tax = subtotal * 0.12;
        const total = subtotal + tax - discount;
        let balance = total - advance;
        if (balance < 0) balance = 0;
    
        document.getElementById("b-subtotal").textContent = "$" + subtotal.toFixed(2);
        document.getElementById("b-tax").textContent = "$" + tax.toFixed(2);
        document.getElementById("b-total").textContent = "$" + total.toFixed(2);
        document.getElementById("b-balance").textContent = "$" + balance.toFixed(2);
        return;
      }
    }
  }
  
  if (document.getElementById("b-subtotal")) {
    document.getElementById("b-nights").textContent = "0";
    document.getElementById("b-subtotal").textContent = "$0.00";
    document.getElementById("b-tax").textContent = "$0.00";
    document.getElementById("b-total").textContent = "$0.00";
    document.getElementById("b-balance").textContent = "$0.00";
  }
};

async function openNewBookingModal() {
  editingBookingId = null;
  document.getElementById("form-booking")?.reset();
  const title = document.querySelector("#modal-booking h3");
  if (title) title.textContent = "Create Reservation";
  const btn = document.querySelector("#modal-booking button[type=submit]");
  if (btn) btn.textContent = "Confirm Reservation";

  // Populate guests
  try {
    const gRes = await fetch("/api/guests", {
      headers: { "Authorization": `Bearer ${currentToken}` }
    });
    if (gRes.ok) {
      const gData = await gRes.json();
      const gSel = document.getElementById("b-guest");
      if (gSel) {
        gSel.innerHTML = `<option value="">— Select Guest Profile —</option>`;
        (gData.guests || []).forEach(g => {
          const opt = document.createElement("option");
          opt.value = g.id;
          opt.textContent = `${g.full_name} (${g.phone})`;
          gSel.appendChild(opt);
        });
      }
    }
  } catch (e) {}

  // Default dates
  const today = new Date().toISOString().split("T")[0];
  const tomorrow = new Date(Date.now() + 86400000).toISOString().split("T")[0];
  const bIn = document.getElementById("b-in");
  const bOut = document.getElementById("b-out");
  if (bIn) bIn.value = today;
  if (bOut) bOut.value = tomorrow;

  // Clear previous subtotal calculations
  document.getElementById("b-nights").textContent = "0";
  document.getElementById("b-subtotal").textContent = "$0.00";
  document.getElementById("b-tax").textContent = "$0.00";
  document.getElementById("b-total").textContent = "$0.00";
  document.getElementById("b-balance").textContent = "$0.00";

  openModal("modal-booking");
  
  // Calculate rooms for default dates
  setTimeout(calculateBooking, 100);
}

async function openEditBookingModal(bookingId) {
  editingBookingId = bookingId;
  const booking = allBookings.find(b => String(b.id) === String(bookingId));
  if (!booking) return;

  document.getElementById("form-booking")?.reset();
  const title = document.querySelector("#modal-booking h3");
  if (title) title.textContent = "Edit Reservation";
  const btn = document.querySelector("#modal-booking button[type=submit]");
  if (btn) btn.textContent = "Save Changes";

  // Populate guests
  try {
    const gRes = await fetch("/api/guests", {
      headers: { "Authorization": `Bearer ${currentToken}` }
    });
    if (gRes.ok) {
      const gData = await gRes.json();
      const gSel = document.getElementById("b-guest");
      if (gSel) {
        gSel.innerHTML = `<option value="">— Select Guest Profile —</option>`;
        (gData.guests || []).forEach(g => {
          const opt = document.createElement("option");
          opt.value = g.id;
          opt.textContent = `${g.full_name} (${g.phone})`;
          gSel.appendChild(opt);
        });
      }
    }
  } catch (e) {}

  // Populate booking data
  const bGuest = document.getElementById("b-guest");
  if (bGuest) bGuest.value = booking.guest_id;
  
  const bIn = document.getElementById("b-in");
  if (bIn) bIn.value = booking.check_in_date;
  
  const bOut = document.getElementById("b-out");
  if (bOut) bOut.value = booking.check_out_date;

  const bAdults = document.getElementById("b-adults");
  if (bAdults) bAdults.value = booking.adults || 1;

  const bChildren = document.getElementById("b-children");
  if (bChildren) bChildren.value = booking.children || 0;

  const bDiscount = document.getElementById("b-discount");
  if (bDiscount) bDiscount.value = booking.discount || 0;

  const bAdvance = document.getElementById("b-advance");
  if (bAdvance) bAdvance.value = booking.advance_payment || 0;

  openModal("modal-booking");
  
  // Calculate available rooms (excluding this booking's current room from overlap)
  // and re-select the room
  setTimeout(() => {
    const bRoom = document.getElementById("b-room");
    if (bRoom) bRoom.value = booking.room_id;
    calculateBooking();
  }, 100);
}

function cancelBooking(bookingId) {
  showConfirm(
    "Cancel Reservation",
    "Are you sure you want to cancel this reservation? The room will be released to inventory.",
    async () => {
      try {
        const res = await fetch(`/api/bookings/${bookingId}`, {
          method: "DELETE",
          headers: { "Authorization": `Bearer ${currentToken}` }
        });
        const data = await res.json();
        if (res.ok && data.success) {
          showToast("success", "Cancelled", data.message || "Reservation has been cancelled.");
          await loadAllData();
        } else {
          showToast("error", "Error", data.message || "Failed to cancel reservation.");
        }
      } catch (e) {
        showToast("error", "Error", "Failed to cancel reservation.");
      }
    }
  );
}

function openAddRoomModal() {
  editingRoomId = null;
  document.getElementById("form-room")?.reset();
  const title = document.querySelector("#modal-room h3");
  if (title) title.textContent = "Add New Room";
  const btn = document.querySelector("#modal-room button[type=submit]");
  if (btn) btn.textContent = "Create Room";
  openModal("modal-room");
}

function openEditRoomModal(roomId) {
  const room = allRooms.find(r => String(r.id) === String(roomId));
  if (!room) return;
  
  editingRoomId = roomId;
  document.getElementById("form-room")?.reset();
  
  const title = document.querySelector("#modal-room h3");
  if (title) title.textContent = "Edit Room Details";
  const btn = document.querySelector("#modal-room button[type=submit]");
  if (btn) btn.textContent = "Save Changes";
  
  const rNum = document.getElementById("r-num");
  const rFloor = document.getElementById("r-floor");
  const rType = document.getElementById("r-type");
  const rBed = document.getElementById("r-bed");
  const rPrice = document.getElementById("r-price");
  const rCap = document.getElementById("r-capacity");
  const rAmen = document.getElementById("r-amenities");
  
  if (rNum) rNum.value = room.room_number || "";
  if (rFloor) rFloor.value = room.floor || 1;
  if (rType) rType.value = room.room_type || "Standard";
  if (rBed) rBed.value = room.bed_type || "Double";
  if (rPrice) rPrice.value = room.price_per_night || 100;
  if (rCap) rCap.value = room.capacity || 2;
  if (rAmen) rAmen.value = room.amenities || "";
  
  openModal("modal-room");
}

function deleteRoom(roomId) {
  const room = allRooms.find(r => String(r.id) === String(roomId));
  const roomNumber = room ? room.room_number : roomId;
  showConfirm(
    "Delete Room",
    `Are you sure you want to permanently delete Room ${roomNumber}? This cannot be undone.`,
    async () => {
      try {
        const res = await fetch(`/api/rooms/${roomId}`, {
          method: "DELETE",
          headers: { "Authorization": `Bearer ${currentToken}` }
        });
        const data = await res.json();
        if (res.ok && data.success) {
          showToast("success", "Deleted", data.message || "Room has been deleted.");
          await loadAllData();
        } else {
          showToast("error", "Error", data.message || data.error || "Failed to delete room.");
        }
      } catch (e) {
        showToast("error", "Error", "Failed to delete room.");
      }
    }
  );
}

function openHKModal(roomNum, status) {
  const rEl = document.getElementById("hk-room");
  const sEl = document.getElementById("hk-status");
  if (rEl) rEl.value = roomNum;
  if (sEl) sEl.value = status || "Clean";
  openModal("modal-hk");
}

async function openAddServiceChargeModal() {
  try {
    const res = await fetch("/api/bookings", {
      headers: { "Authorization": `Bearer ${currentToken}` }
    });
    if (res.ok) {
      const data = await res.json();
      const sel = document.getElementById("s-booking");
      if (sel) {
        sel.innerHTML = `<option value="">— Select Active Booking —</option>`;
        (data.bookings || []).filter(b => b.status === "Checked-in").forEach(b => {
          const opt = document.createElement("option");
          opt.value = b.id;
          opt.textContent = `${b.booking_code} — ${b.guest_name} (Room ${b.room_number})`;
          sel.appendChild(opt);
        });
      }
    }
  } catch (e) {}

  openModal("modal-service");
}

function openAddUserModal() {
  document.getElementById("form-user")?.reset();
  openModal("modal-user");
}

function toggleNotifications() {
  showToast("info", "Grand Horizon Concierge", "All systems operational. No unacknowledged guest alarms.");
}

// ==========================================================================
// 16. CONFIRMATION DIALOG
// ==========================================================================
let _confirmCallback = null;

function showConfirm(title, message, onConfirm) {
  const titleEl = document.getElementById("confirm-title");
  const msgEl   = document.getElementById("confirm-message");
  const btn     = document.getElementById("confirm-proceed-btn");

  if (titleEl) titleEl.textContent = title;
  if (msgEl)   msgEl.textContent   = message;
  _confirmCallback = onConfirm;
  openModal("modal-confirm");

  if (btn) {
    btn.onclick = () => {
      closeModal("modal-confirm");
      if (_confirmCallback) _confirmCallback();
      _confirmCallback = null;
    };
  }
}

function cancelConfirm() {
  _confirmCallback = null;
  closeModal("modal-confirm");
}

// ==========================================================================
// 17. TOAST NOTIFICATIONS
// ==========================================================================
const TOAST_ICONS = {
  success: `<svg viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>`,
  error:   `<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>`,
  warning: `<svg viewBox="0 0 24 24"><path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>`,
  info:    `<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>`
};

function showToast(type, title, message) {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <div class="toast-icon">${TOAST_ICONS[type] || TOAST_ICONS.info}</div>
    <div class="toast-body">
      <div class="toast-title">${title}</div>
      ${message ? `<div class="toast-message">${message}</div>` : ""}
    </div>
    <button class="toast-close" onclick="dismissToast(this.parentElement)" aria-label="Dismiss">
      <svg viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
    </button>
  `;

  container.appendChild(toast);
  setTimeout(() => dismissToast(toast), 4200);
}

function dismissToast(toast) {
  if (!toast || toast.classList.contains("removing")) return;
  toast.classList.add("removing");
  setTimeout(() => toast.remove(), 260);
}

// ==========================================================================
// 18. EVENT LISTENERS & FORM SUBMISSIONS
// ==========================================================================
function setupEventListeners() {

  // Login Form
  document.getElementById("form-login")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const user = document.getElementById("login-user")?.value.trim();
    const pass = document.getElementById("login-pass")?.value.trim();
    const btn  = e.target.querySelector("[type=submit]");

    if (btn) { btn.disabled = true; btn.textContent = "Authenticating…"; }

    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: user, password: pass })
      });
      const data = await res.json();

      if (res.ok && data.success && data.user) {
        currentToken = data.user.token;
        localStorage.setItem("hms_auth_token", currentToken);
        currentUser = data.user;
        showAuthScreen(false);
        applyRBAC();
        await loadAllData();
        initAutoSync();
        showToast("success", "Welcome to Grand Horizon", `Authenticated as ${data.user.full_name}`);
      } else {
        showToast("error", "Access Denied", data.message || data.error || "Invalid credentials.");
      }
    } catch (err) {
      showToast("error", "Connection Error", "Unable to connect to hotel backend. Check network.");
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = `<svg viewBox="0 0 24 24"><path d="M11 7L9.6 8.4l2.6 2.6H2v2h10.2l-2.6 2.6L11 17l5-5-5-5zm9 12h-8v2h8c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2h-8v2h8v14z"/></svg> Enter Portal`;
      }
    }
  });

  // Guest Registration & Edit
  document.getElementById("form-guest")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const full_name = document.getElementById("g-name")?.value.trim();
    const phone = document.getElementById("g-phone")?.value.trim();

    if (!full_name || !phone) {
      showToast("error", "Validation Error", "Full name and phone number are required.");
      return;
    }

    const body = {
      full_name:       full_name,
      phone:           phone,
      email:           document.getElementById("g-email")?.value.trim(),
      city:            document.getElementById("g-city")?.value.trim(),
      id_proof_type:   document.getElementById("g-idtype")?.value.trim(),
      id_proof_number: document.getElementById("g-idnum")?.value.trim()
    };

    try {
      const url = editingGuestId ? `/api/guests/${editingGuestId}` : "/api/guests";
      const method = editingGuestId ? "PUT" : "POST";
      const res = await fetch(url, {
        method: method,
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${currentToken}` },
        body: JSON.stringify(body)
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast("success", editingGuestId ? "Profile Updated" : "Guest Profile Saved", data.message);
        closeModal("modal-guest");
        editingGuestId = null;
        await loadAllData();
      } else {
        showToast("error", "Registration Failed", data.message || data.error || "Failed to save guest.");
      }
    } catch (err) {
      showToast("error", "Error", "Failed to save guest profile.");
    }
  });

  // Reservation Form (with overlap prevention)
  document.getElementById("form-booking")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = {
      guest_id:        document.getElementById("b-guest")?.value,
      room_id:         document.getElementById("b-room")?.value,
      check_in_date:   document.getElementById("b-in")?.value,
      check_out_date:  document.getElementById("b-out")?.value,
      adults:          parseInt(document.getElementById("b-adults")?.value) || 1,
      children:        parseInt(document.getElementById("b-children")?.value) || 0,
      discount:        parseFloat(document.getElementById("b-discount")?.value) || 0,
      advance_payment: parseFloat(document.getElementById("b-advance")?.value) || 0
    };

    const method = editingBookingId ? "PUT" : "POST";
    const endpoint = editingBookingId ? `/api/bookings/${editingBookingId}` : "/api/bookings";

    try {
      const res = await fetch(endpoint, {
        method: method,
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${currentToken}` },
        body: JSON.stringify(body)
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast("success", "Reservation Saved", data.message);
        closeModal("modal-booking");
        await loadAllData();
      } else {
        showToast("error", "Booking Conflict", data.message || data.error || "Overlap detected.");
      }
    } catch (err) {
      showToast("error", "Error", "Failed to save reservation.");
    }
  });

  // Guided Wizard Check-In Form
  document.getElementById("wizard-checkin-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const roomNum = document.getElementById("wiz-ci-room")?.value;
    const gName   = document.getElementById("wiz-ci-guest")?.value.trim();
    const nights  = parseInt(document.getElementById("wiz-ci-nights")?.value) || 1;

    try {
      const res = await fetch("/api/check-in", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${currentToken}` },
        body: JSON.stringify({ room_num: roomNum, guest_name: gName, nights: nights })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast("success", "Check-In Confirmed", data.message);
        document.getElementById("wizard-checkin-form")?.reset();
        nextCheckInStep(1);
        await loadAllData();
      } else {
        showToast("error", "Check-In Error", data.message || data.error || "Failed to check in.");
      }
    } catch (err) {
      showToast("error", "Error", "Failed to process check-in.");
    }
  });

  // Guided Wizard Check-Out Form
  document.getElementById("wizard-checkout-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const roomNum = document.getElementById("wiz-co-room")?.value;
    const services = parseFloat(document.getElementById("wiz-co-services")?.value) || 0;

    try {
      const res = await fetch("/api/check-out", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${currentToken}` },
        body: JSON.stringify({ room_num: roomNum, services: services })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast("success", "Check-Out Processed", data.message);
        document.getElementById("wizard-checkout-form")?.reset();
        await loadAllData();
        if (data.invoice) {
          renderPrintableInvoice(data.invoice);
        }
      } else {
        showToast("error", "Check-Out Error", data.message || data.error || "Failed to process check-out.");
      }
    } catch (err) {
      showToast("error", "Error", "Failed to process check-out.");
    }
  });

  // Add / Edit Property Room (Admin only)
  document.getElementById("form-room")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const room_number = document.getElementById("r-num")?.value.trim();
    const price_per_night = parseFloat(document.getElementById("r-price")?.value) || 0;

    if (!room_number) {
      showToast("error", "Validation Error", "Room number is required.");
      return;
    }
    if (price_per_night <= 0) {
      showToast("error", "Validation Error", "Price per night must be greater than 0.");
      return;
    }

    const body = {
      room_number:     room_number,
      floor:           parseInt(document.getElementById("r-floor")?.value) || 1,
      room_type:       document.getElementById("r-type")?.value,
      bed_type:        document.getElementById("r-bed")?.value,
      price_per_night: price_per_night,
      capacity:        parseInt(document.getElementById("r-capacity")?.value) || 2,
      amenities:       document.getElementById("r-amenities")?.value.trim()
    };

    try {
      const url = editingRoomId ? `/api/rooms/${editingRoomId}` : "/api/rooms";
      const method = editingRoomId ? "PUT" : "POST";
      const res = await fetch(url, {
        method: method,
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${currentToken}` },
        body: JSON.stringify(body)
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast("success", editingRoomId ? "Room Updated" : "Room Added", data.message);
        closeModal("modal-room");
        editingRoomId = null;
        await loadAllData();
      } else {
        showToast("error", "Error", data.message || data.error || "Failed to save room.");
      }
    } catch (err) {
      showToast("error", "Error", "Failed to save room.");
    }
  });

  // Add Service Charge
  document.getElementById("form-add-service")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = {
      booking_id:   document.getElementById("s-booking")?.value,
      service_name: document.getElementById("s-name")?.value.trim(),
      quantity:     parseInt(document.getElementById("s-qty")?.value) || 1,
      unit_price:   parseFloat(document.getElementById("s-price")?.value) || 0
    };

    try {
      const res = await fetch("/api/services/add-to-booking", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${currentToken}` },
        body: JSON.stringify(body)
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast("success", "Charge Added", data.message);
        closeModal("modal-service");
        await loadAllData();
      } else {
        showToast("error", "Error", data.message || data.error || "Failed to add charge.");
      }
    } catch (err) {
      showToast("error", "Error", "Failed to add service charge.");
    }
  });

  // Housekeeping Form
  document.getElementById("form-hk")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = {
      room_number:     document.getElementById("hk-room")?.value,
      cleaning_status: document.getElementById("hk-status")?.value,
      assigned_staff:  document.getElementById("hk-staff")?.value
    };

    try {
      const res = await fetch("/api/housekeeping", {
        method: "PUT",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${currentToken}` },
        body: JSON.stringify(body)
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast("success", "Status Updated", data.message);
        closeModal("modal-hk");
        await loadAllData();
      } else {
        showToast("error", "Error", data.message || data.error || "Failed to update housekeeping.");
      }
    } catch (err) {
      showToast("error", "Error", "Failed to update housekeeping.");
    }
  });

  // Add Staff User Form
  document.getElementById("form-user")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = {
      username:  document.getElementById("u-username")?.value.trim(),
      password:  document.getElementById("u-password")?.value.trim(),
      full_name: document.getElementById("u-fullname")?.value.trim(),
      role:      document.getElementById("u-role")?.value
    };

    try {
      const res = await fetch("/api/auth/users", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${currentToken}` },
        body: JSON.stringify(body)
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast("success", "Staff Account Created", data.message);
        closeModal("modal-user");
        loadUsers();
        await loadAllData();
      } else {
        showToast("error", "Error", data.message || data.error || "Failed to create user.");
      }
    } catch (err) {
      showToast("error", "Error", "Failed to create staff account.");
    }
  });

  // Omnibox Global Search
  document.getElementById("global-search")?.addEventListener("input", (e) => {
    const q = e.target.value.trim().toLowerCase();
    if (!q) return;

    if (document.getElementById("view-guests")?.classList.contains("active")) {
      loadGuests(q);
    } else if (document.getElementById("view-rooms")?.classList.contains("active")) {
      const searchInput = document.getElementById("room-search");
      if (searchInput) { searchInput.value = q; filterRooms(); }
    } else if (document.getElementById("view-bookings")?.classList.contains("active")) {
      const searchInput = document.getElementById("booking-search");
      if (searchInput) { searchInput.value = q; filterBookings(); }
    }
  });

  // Keyboard Shortcuts: Escape to close modals/drawers, Cmd/Ctrl+K to focus omnibox
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      document.querySelectorAll(".modal-overlay.active").forEach(m => m.classList.remove("active"));
      document.querySelectorAll(".drawer-overlay.active").forEach(d => d.classList.remove("active"));
    }
    if ((e.metaKey || e.ctrlKey) && e.key === "k") {
      e.preventDefault();
      document.getElementById("global-search")?.focus();
    }
  });
}

// ==========================================================================
// 19. UTILITY HELPERS
// ==========================================================================
function renderEmptyState(iconSvg, title, message, actionBtnHtml = "") {
  return `
    <div class="empty-state-luxury">
      <div class="empty-state-icon">
        ${iconSvg || `<svg viewBox="0 0 24 24"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H5V5h14v14z"/></svg>`}
      </div>
      <div class="empty-state-title">${title}</div>
      <div class="empty-state-desc">${message}</div>
      ${actionBtnHtml ? `<div class="empty-state-action">${actionBtnHtml}</div>` : ""}
    </div>
  `;
}

function renderTableSkeleton(tbody, cols = 6, rows = 4) {
  if (!tbody) return;
  let html = "";
  for (let r = 0; r < rows; r++) {
    html += `<tr class="skeleton-table-row">`;
    for (let c = 0; c < cols; c++) {
      const width = c === 0 ? "40%" : c === 1 ? "75%" : "55%";
      html += `<td><div class="skeleton-cell" style="width:${width};"></div></td>`;
    }
    html += `</tr>`;
  }
  tbody.innerHTML = html;
}

function formatDate(dateStr) {
  if (!dateStr) return "—";
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return dateStr;
  }
}

function escapeHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
