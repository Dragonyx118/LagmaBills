#!/bin/bash
# pi_stats.sh — LagmaBills
# Stampa una riga compatta: CPU% | RAM% (usata/tot) | Temp

cpu_stat() {
    read -r _ u n s i io irq sirq st _ < /proc/stat
    idle1=$((i + io))
    total1=$((u + n + s + i + io + irq + sirq + st))
    sleep 0.3
    read -r _ u n s i io irq sirq st _ < /proc/stat
    idle2=$((i + io))
    total2=$((u + n + s + i + io + irq + sirq + st))
    diff_idle=$((idle2 - idle1))
    diff_total=$((total2 - total1))
    if [ "$diff_total" -gt 0 ]; then
        echo $(( (100 * (diff_total - diff_idle)) / diff_total ))
    else
        echo 0
    fi
}

CPU=$(cpu_stat)

read -r _ mem_tot mem_used _ < <(free -m | awk '/Mem:/ {print $1, $2, $3}')
RAM_PCT=$(( 100 * mem_used / mem_tot ))

if command -v vcgencmd >/dev/null 2>&1; then
    TEMP=$(vcgencmd measure_temp | grep -oP '[\d.]+')
else
    TEMP=$(awk '{printf "%.1f", $1/1000}' /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo "?")
fi

if (( $(echo "$TEMP > 70" | bc -l 2>/dev/null || echo 0) )); then
    TCOLOR="colour196"
elif (( $(echo "$TEMP > 60" | bc -l 2>/dev/null || echo 0) )); then
    TCOLOR="colour214"
else
    TCOLOR="colour46"
fi

printf "#[fg=colour87]CPU:%s%%#[fg=white] | #[fg=colour87]RAM:%s%% (%sM/%sM)#[fg=white] | #[fg=%s]%s°C#[default]" \
    "$CPU" "$RAM_PCT" "$mem_used" "$mem_tot" "$TCOLOR" "$TEMP"
