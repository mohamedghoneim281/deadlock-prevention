// Timed execution engine: the C++ twin of petri/timed.py.
//
// Rules (identical to the Python reference, so logs can be compared byte for byte):
//  * integer-tick time; a transition with delay > 0 has one timer that starts when it becomes
//    enabled and fires `delay` ticks later (single server, enabling memory);
//  * a transition with delay == 0 is "immediate" and fired by the dispatcher.
// At every event time t:
//   1. inject external arrivals due at t                       -> "t ARRIVE place n"
//   2. fire timed transitions whose timer expires at t (net order) -> "t FIRE name"
//   3. dispatch: fire the FIRST enabled immediate transition in net order, repeat until none
//   4. start timers of newly enabled timed transitions, drop timers of disabled ones
// The run ends when no timer and no arrival is pending: DONE if the goal marking is reached
// on the goal places, DEADLOCK otherwise.
#pragma once
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <limits>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#include "petri_net.hpp"

namespace petri {

struct Arrival {
    int64_t time;
    int place;
    int count;
};

struct Scenario {
    std::vector<Arrival> arrivals;                 // stable-sorted by time
    std::vector<std::pair<int, int>> goal;         // (place, tokens) that define "batch done"

    static Scenario load(const Net& net, const std::string& path) {
        std::ifstream in(path);
        if (!in) throw std::runtime_error("cannot open scenario file: " + path);
        Scenario sc;
        std::string line;
        while (std::getline(in, line)) {
            if (line.empty() || line[0] == '#') continue;
            std::istringstream ss(line);
            std::string kw, pn;
            ss >> kw;
            if (kw == "arrive") {
                Arrival a;
                ss >> a.time >> pn >> a.count;
                a.place = net.place_index.at(pn);
                sc.arrivals.push_back(a);
            } else if (kw == "goal") {
                int tokens;
                ss >> pn >> tokens;
                sc.goal.emplace_back(net.place_index.at(pn), tokens);
            } else {
                throw std::runtime_error("unknown keyword in scenario file: " + kw);
            }
        }
        std::stable_sort(sc.arrivals.begin(), sc.arrivals.end(),
                         [](const Arrival& a, const Arrival& b) { return a.time < b.time; });
        return sc;
    }
};

struct RunResult {
    bool done = false;
    int64_t end_time = 0;
    Marking final_marking;
    int64_t fired = 0;  // number of transition firings (events handled)
};

class Simulator {
public:
    Simulator(const Net& net, const Scenario& sc) : net_(net), sc_(sc) {
        timer_.assign(net.transitions.size(), kNone);
    }

    // log != nullptr -> append reference-format log lines.
    // step_ns != nullptr -> append the wall-clock cost (ns) of every event-time step.
    RunResult run(std::vector<std::string>* log = nullptr, std::vector<int64_t>* step_ns = nullptr) {
        using clk = std::chrono::steady_clock;
        const int T = static_cast<int>(net_.transitions.size());
        Marking m = net_.m0;
        std::fill(timer_.begin(), timer_.end(), kNone);
        size_t ai = 0;
        int64_t t = 0;
        int64_t fired = 0;
        auto do_arrivals = [&](int64_t now) {
            while (ai < sc_.arrivals.size() && sc_.arrivals[ai].time == now) {
                const Arrival& a = sc_.arrivals[ai];
                m[a.place] += a.count;
                if (log) log->push_back(std::to_string(now) + " ARRIVE " + net_.places[a.place] + " " + std::to_string(a.count));
                ++ai;
            }
        };
        do_arrivals(0);
        for (;;) {
            clk::time_point t0;
            if (step_ns) t0 = clk::now();
            // 2. expired timers
            for (int ti = 0; ti < T; ++ti) {
                if (timer_[ti] == t) {
                    net_.fire(m, ti);
                    timer_[ti] = kNone;
                    ++fired;
                    if (log) log->push_back(std::to_string(t) + " FIRE " + net_.transitions[ti].name);
                }
            }
            // 3. dispatch
            for (bool progress = true; progress;) {
                progress = false;
                for (int ti = 0; ti < T; ++ti) {
                    if (net_.transitions[ti].delay == 0 && net_.enabled(m, ti)) {
                        net_.fire(m, ti);
                        ++fired;
                        if (log) log->push_back(std::to_string(t) + " FIRE " + net_.transitions[ti].name);
                        progress = true;
                        if (fired > kMaxFirings) throw std::runtime_error("dispatch did not terminate");
                        break;
                    }
                }
            }
            // 4. timers
            int64_t next = kNone;
            for (int ti = 0; ti < T; ++ti) {
                const int64_t d = net_.transitions[ti].delay;
                if (d > 0) {
                    const bool en = net_.enabled(m, ti);
                    if (en && timer_[ti] == kNone) timer_[ti] = t + d;
                    else if (!en) timer_[ti] = kNone;
                }
                if (timer_[ti] != kNone && (next == kNone || timer_[ti] < next)) next = timer_[ti];
            }
            if (ai < sc_.arrivals.size() && (next == kNone || sc_.arrivals[ai].time < next))
                next = sc_.arrivals[ai].time;
            if (step_ns) step_ns->push_back(std::chrono::duration_cast<std::chrono::nanoseconds>(clk::now() - t0).count());
            if (next == kNone) break;
            t = next;
            do_arrivals(t);
        }
        RunResult r;
        r.done = true;
        for (auto& [p, tok] : sc_.goal) r.done = r.done && (m[p] == tok);
        r.end_time = t;
        r.final_marking = m;
        r.fired = fired;
        if (log) log->push_back("END " + std::to_string(t) + (r.done ? " DONE" : " DEADLOCK"));
        return r;
    }

private:
    static constexpr int64_t kNone = std::numeric_limits<int64_t>::min();
    static constexpr int64_t kMaxFirings = 100000000;
    const Net& net_;
    const Scenario& sc_;
    std::vector<int64_t> timer_;
};

}  // namespace petri
