const API_BASE_URL = "http://localhost:8000";

// set default start date to first day of current month
function setDefaultStartDate() {
  const input = document.getElementById("startDate");
  if (!input) return;
  const now = new Date();
  const first = new Date(now.getFullYear(), now.getMonth(), 1);
  input.value = first.toISOString().slice(0, 10);
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
              title="${day.date}: ${day.total_miles} miles"
            >
              ${dayNumber}
            </div>
          `;
        })
        .join("");

      return `
        <div class="month-section">
          <h3>${month} — ${mileageByMonth[month] || 0} miles</h3>

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