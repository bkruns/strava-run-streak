const API_BASE_URL = "http://localhost:8000";

// set default start date to first day of current month
function setDefaultStartDate() {
  const input = document.getElementById("startDate");
  if (!input) return;
  const now = new Date();
  const first = new Date(now.getFullYear(), now.getMonth(), 1);
  input.value = first.toISOString().slice(0, 10);
}

// latest loaded data for sharing
let latestData = null;

// format `YYYY-MM-DD` -> "May 18, 2026"
function formatDisplayDate(dateStr) {
  const d = new Date(dateStr);
  return d.toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" });
}

// format `YYYY-MM-DDTHH:00` -> "May 18, 2026 7:00am"
function formatWeatherHour(hourStr) {
  const d = new Date(hourStr);
  const datePart = d.toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" });
  let timePart = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", hour12: true });
  timePart = timePart.replace(" AM", "am").replace(" PM", "pm");
  return `${datePart} ${timePart}`;
}

function loginToStrava() {
  const width = 600;
  const height = 700;
  const left = window.screen.width / 2 - width / 2;
  const top = window.screen.height / 2 - height / 2;

  const loginWindow = window.open(
    `${API_BASE_URL}/login`,
    "Strava Login",
    `width=${width},height=${height},top=${top},left=${left}`
  );

  const timer = setInterval(() => {
    if (loginWindow.closed) {
      clearInterval(timer);
      loadStreak();
    }
  }, 1000);
}

function groupDaysByMonth(dailyTotals) {
  const grouped = {};

  dailyTotals.forEach((day) => {
    const month = day.date.substring(0, 7);

    if (!grouped[month]) {
      grouped[month] = [];
    }

    grouped[month].push(day);
  });

  return grouped;
}

function formatMonthLabel(monthKey) {
  const [year, month] = monthKey.split("-");
  const date = new Date(parseInt(year, 10), parseInt(month, 10) - 1, 1);
  return date.toLocaleString(undefined, { month: "long", year: "numeric" });
}

function renderMonthlyMileageAndGrid(data) {
  const mileageByMonth = {};

  data.monthly_totals.forEach((month) => {
    mileageByMonth[month.month] = month.total_miles;
  });

  const grouped = groupDaysByMonth(data.daily_totals);

  return Object.entries(grouped)
    .sort(([monthA], [monthB]) => monthB.localeCompare(monthA))
    .map(([month, days]) => {
      const firstDate = new Date(days[0].date + "T00:00:00");
      const firstWeekday = firstDate.getDay();

      const blanks = Array(firstWeekday)
        .fill('<div class="blank"></div>')
        .join("");

      const dayCells = days
        .map((day) => {
          const dayNumber = new Date(day.date + "T00:00:00").getDate();

          return `
                <div
                  class="day ${day.run_count === 0 ? "missed" : ""}"
                  data-date="${day.date}"
                  title="${day.date}: ${day.total_miles} miles"
                >
                  ${dayNumber}
                </div>
              `;
        })
        .join("");

      return `
        <div class="month-section">
          <h3>${formatMonthLabel(month)} — ${mileageByMonth[month] || 0} miles</h3>

          <div class="weekday-header">
            <div>Sun</div>
            <div>Mon</div>
            <div>Tue</div>
            <div>Wed</div>
            <div>Thu</div>
            <div>Fri</div>
            <div>Sat</div>
          </div>

          <div class="month-grid">
            ${blanks}
            ${dayCells}
          </div>
        </div>
      `;
    })
    .join("");
}

async function loadStreak() {
  const loading = document.getElementById("loading");
  const app = document.getElementById("app");
  const start = document.getElementById("startDate").value;

  loading.classList.remove("hidden");
  app.innerHTML = "";

  try {
    const response = await fetch(`${API_BASE_URL}/run-streak?start=${start}`);

    if (!response.ok) {
      if (response.status === 401) {
        loginToStrava();
        return;
      }

      const error = await response.json();

      app.innerHTML = `
        <div class="card">
          <h2>Unable to Load Data</h2>
          <p>${error.error || "Unknown error"}</p>
          <p>Try logging into Strava first.</p>
        </div>
      `;

      return;
    }

    const data = await response.json();

    // store for share/export
    latestData = data;

    app.innerHTML = `
      <div class="grid">
        <div class="card">
          <div>Streak Active</div>
          <div class="big">${data.streak_active ? "YES 🔥" : "NO 😬"}</div>
        </div>

        <div class="card">
          <div>Total Days</div>
          <div class="big">${data.total_days}</div>
        </div>

        <div class="card">
          <div>Run Days</div>
          <div class="big">${data.run_days}</div>
        </div>

        <div class="card">
          <div>Total Runs</div>
          <div class="big">${data.total_runs}</div>
        </div>

        <div class="card">
          <div>Total Miles</div>
          <div class="big">${data.total_miles}</div>
        </div>

        <div class="card">
          <div>Avg Miles / Run Day</div>
          <div class="big">${data.average_miles_per_run_day}</div>
        </div>
      </div>

      <div class="card">
        <h2>Longest Total Run Day</h2>
        <p>
          ${
            data.longest_total_run_day
              ? `${data.longest_total_run_day.date} — ${data.longest_total_run_day.total_miles} miles`
              : "N/A"
          }
        </p>

        <h2>Shortest Total Run Day</h2>
        <p>
          ${
            data.shortest_total_run_day
              ? `${data.shortest_total_run_day.date} — ${data.shortest_total_run_day.total_miles} miles`
              : "N/A"
          }
        </p>
      </div>

      <div class="card">
        <h2>Monthly Mileage & Daily Grid</h2>
        ${renderMonthlyMileageAndGrid(data)}
      </div>

      <div class="card">
        <h2>Missed Days</h2>
        <p>
          ${
            data.missed_days.length > 0
              ? data.missed_days.join(", ")
              : "None 🎉"
          }
        </p>
      </div>

      <div class="footer">
        Generated from Strava API data
      </div>
    `;
    // attach click handlers for day details
    attachDayClickHandlers();
  } catch (err) {
    app.innerHTML = `
      <div class="card">
        <h2>Error</h2>
        <p>${err.message}</p>
      </div>
    `;
  } finally {
    loading.classList.add("hidden");
  }
}

// initialize the default date before loading
setDefaultStartDate();
loadStreak();

// attach click handlers for day elements (idempotent)
function attachDayClickHandlers() {
  const appEl = document.getElementById("app");
  if (!appEl || appEl._dayHandlerAttached) return;

  appEl.addEventListener("click", (e) => {
    const dayEl = e.target.closest(".day");
    if (!dayEl) return;
    const date = dayEl.getAttribute("data-date");
    if (date) loadDayDetails(date);
  });

  appEl._dayHandlerAttached = true;
}

async function loadDayDetails(date) {
  const loading = document.getElementById("loading");
  if (loading) loading.classList.remove("hidden");

  try {
    const resp = await fetch(`${API_BASE_URL}/day-details?date=${date}`);
    if (!resp.ok) {
      if (resp.status === 401) {
        loginToStrava();
        return;
      }
      const err = await resp.json();
      alert(err.error || "Unable to load day details");
      return;
    }

    const data = await resp.json();

    // build details panel
    let html = `
      <div class="details-card">
        <button class="close">✖</button>
        <h2>Details for ${formatDisplayDate(data.date)}</h2>
        <p><strong>Total Miles:</strong> ${data.total_miles} — <strong>Runs:</strong> ${data.run_count}</p>
        <h3>Activities</h3>
        <ul class="activity-list">
    `;

    if (data.activities.length === 0) {
      html += `<li>No activities for this date.</li>`;
    } else {
      data.activities.forEach((a) => {
        html += `<li><strong>${a.name}</strong> — ${a.miles} mi — ${a.moving_time_minutes} min`;
        if (a.treadmill) {
          html += ` — Treadmill`;
        }
        if (a.avg_miles_per_minute) {
          // convert miles/min -> minutes per mile
          const mpm = Number(a.avg_miles_per_minute);
          if (mpm > 0) {
            const secondsPerMile = 60 / mpm;
            const minutes = Math.floor(secondsPerMile / 60);
            const seconds = Math.round(secondsPerMile % 60);
            const secStr = String(seconds).padStart(2, "0");
            html += ` — Pace: ${minutes}:${secStr}/mi`;
          }
        }
        if (a.weather) {
          html += ` — ${a.weather.temperature_f}°F at ${formatWeatherHour(a.weather.weather_hour)}`;
        }
        html += `</li>`;
      });
    }

    html += `</ul></div>`;

    let container = document.getElementById("day-details-container");
    if (!container) {
      container = document.createElement("div");
      container.id = "day-details-container";
      document.body.appendChild(container);
    }

    container.innerHTML = html;
    container.classList.remove("hidden");

    const closeBtn = container.querySelector(".close");
    if (closeBtn) closeBtn.onclick = () => (container.classList.add("hidden"));
  } catch (err) {
    alert(err.message || "Error loading details");
  } finally {
    if (loading) loading.classList.add("hidden");
  }
}

// create an Instagram-story-friendly image (1080x1920)
function createShareImage() {
  if (!latestData) {
    loginToStrava();
    return;
  }

  const canvas = document.createElement("canvas");
  canvas.width = 1080;
  canvas.height = 1920;
  const ctx = canvas.getContext("2d");

  const logo = new Image();
  logo.src = "bkruns-transparent.png";

  function drawShareImage() {
    // background
    const grad = ctx.createLinearGradient(0, 0, 0, canvas.height);
    grad.addColorStop(0, "#0f172a");
    grad.addColorStop(1, "#071024");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const padding = 60;
    const logoSize = 108;
    const contentWidth = canvas.width - padding * 2;

    // logo
    if (logo.complete && logo.naturalWidth) {
      ctx.drawImage(logo, padding, padding, logoSize, logoSize);
    } else {
      ctx.fillStyle = "#fff";
      ctx.fillRect(padding, padding, logoSize, logoSize);
    }

    // streak status
    ctx.fillStyle = "#fff";
    ctx.font = "bold 58px Arial, sans-serif";
    ctx.textBaseline = "middle";
    const statusY = padding + logoSize / 2;
    ctx.fillStyle = latestData.streak_active ? "#34d399" : "#f97316";
    ctx.fillText(latestData.streak_active ? "Run Streak Continues" : "Streak Ended", padding + logoSize + 28, statusY);
    ctx.textBaseline = "alphabetic";

    const statsY = padding + 190;
    const statsHeight = 180;
    ctx.fillStyle = "rgba(15, 23, 42, 0.88)";
    ctx.fillRect(padding - 20, statsY - 20, contentWidth + 40, statsHeight);
    ctx.strokeStyle = "rgba(255, 255, 255, 0.1)";
    ctx.strokeRect(padding - 20, statsY - 20, contentWidth + 40, statsHeight);

    // key stats block
    ctx.fillStyle = "#fff";
    ctx.font = "34px Arial, sans-serif";
    ctx.fillText(`Total Miles: ${latestData.total_miles}`, padding, statsY + 10);
    ctx.fillText(`Run Days: ${latestData.run_days}`, padding, statsY + 72);
    ctx.fillText(`Avg / Run Day: ${latestData.average_miles_per_run_day}`, padding, statsY + 134);

    const grouped = {};
    latestData.daily_totals.forEach((day) => {
      const month = day.date.substring(0, 7);
      if (!grouped[month]) grouped[month] = [];
      grouped[month].push(day);
    });

    const months = Object.keys(grouped).sort((a, b) => b.localeCompare(a));
    const latestMonth = months.length ? months[0] : null;

    if (latestMonth) {
      const monthData = grouped[latestMonth];
      const [yearStr, monthStr] = latestMonth.split("-");
      const year = parseInt(yearStr, 10);
      const monthIndex = parseInt(monthStr, 10) - 1;
      const firstDate = new Date(year, monthIndex, 1);
      const firstWeekday = firstDate.getDay();
      const daysInMonth = new Date(year, monthIndex + 1, 0).getDate();

      const totalMiles = latestData.monthly_totals.find((m) => m.month === latestMonth)?.total_miles || 0;
      const cellSize = 96;
      const gap = 14;
      const gridWidth = 7 * cellSize + 6 * gap;
      const gridX = Math.max(padding, (canvas.width - gridWidth) / 2);
      const gridY = padding + 440;

      ctx.font = "bold 36px Arial, sans-serif";
      ctx.fillStyle = "#fff";
      ctx.fillText(`${formatMonthLabel(latestMonth)} — ${totalMiles} miles`, padding, gridY - 42);

      const weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
      ctx.font = "22px Arial, sans-serif";
      weekdays.forEach((label, idx) => {
        ctx.fillStyle = "#cbd5e1";
        ctx.fillText(label, gridX + idx * (cellSize + gap) + 18, gridY - 2);
      });

      const dayMap = {};
      monthData.forEach((entry) => {
        dayMap[entry.date] = entry;
      });

      for (let row = 0; row < 6; row++) {
        for (let col = 0; col < 7; col++) {
          const cellX = gridX + col * (cellSize + gap);
          const cellY = gridY + row * (cellSize + gap);
          const calendarDay = row * 7 + col - firstWeekday + 1;

          if (calendarDay < 1 || calendarDay > daysInMonth) {
            ctx.fillStyle = "rgba(255, 255, 255, 0.05)";
            ctx.fillRect(cellX, cellY, cellSize, cellSize);
            continue;
          }

          const dateKey = `${yearStr}-${monthStr.padStart(2, "0")}-${String(calendarDay).padStart(2, "0")}`;
          const entry = dayMap[dateKey];
          const ran = entry && entry.run_count > 0;

          ctx.fillStyle = ran ? "#34d399" : "#1f2937";
          ctx.fillRect(cellX, cellY, cellSize, cellSize);
          ctx.strokeStyle = "rgba(255, 255, 255, 0.08)";
          ctx.strokeRect(cellX, cellY, cellSize, cellSize);

          ctx.fillStyle = ran ? "#02160d" : "#d1d5db";
          ctx.font = "bold 26px Arial, sans-serif";
          ctx.fillText(String(calendarDay), cellX + 16, cellY + 48);
        }
      }
    }

    canvas.toBlob(function (blob) {
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
    }, "image/png");
  }

  if (logo.complete && logo.naturalWidth) {
    drawShareImage();
  } else {
    logo.onload = drawShareImage;
    logo.onerror = drawShareImage;
  }
}
