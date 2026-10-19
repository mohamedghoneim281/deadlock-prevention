// petri_engine -- C++ execution engine for the manufacturing-cell Petri net.
//
//   petri_engine simulate <net.txt> <scenario.txt>        timed run, prints the event log
//   petri_engine replay   <net.txt> <trace.txt>           replay a firing/arrival sequence and
//                                                         print marking + enabled set per step
//   petri_engine bench    <net.txt> <scenario.txt> <reps> timing and memory report (JSON)
//
// Exit codes: 0 ok, 1 usage/IO error, 2 replay hit a transition that is not enabled.
#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <numeric>

#ifdef __unix__
#include <sys/resource.h>
#endif
#ifdef __APPLE__
#include <sys/resource.h>
#endif

#include "engine.hpp"
#include "petri_net.hpp"

using namespace petri;

static std::string marking_str(const Marking& m) {
    std::string s;
    for (size_t i = 0; i < m.size(); ++i) {
        if (i) s += ',';
        s += std::to_string(m[i]);
    }
    return s;
}

static std::string enabled_str(const Net& net, const Marking& m) {
    std::string s;
    for (size_t t = 0; t < net.transitions.size(); ++t)
        if (net.enabled(m, static_cast<int>(t))) {
            if (!s.empty()) s += ',';
            s += net.transitions[t].name;
        }
    return s.empty() ? "-" : s;
}

static void print_step(const Net& net, int step, const std::string& label, const Marking& m) {
    std::cout << step << '|' << label << '|' << marking_str(m) << '|' << enabled_str(net, m) << '\n';
}

static int cmd_simulate(const Net& net, const std::string& scen_path) {
    Scenario sc = Scenario::load(net, scen_path);
    Simulator sim(net, sc);
    std::vector<std::string> log;
    sim.run(&log);
    for (const auto& l : log) std::cout << l << '\n';
    return 0;
}

// Trace lines: [<time>] FIRE <transition> | [<time>] ARRIVE <place> <n> | END ... (ignored)
static int cmd_replay(const Net& net, const std::string& trace_path) {
    std::ifstream in(trace_path);
    if (!in) { std::cerr << "cannot open trace " << trace_path << "\n"; return 1; }
    Marking m = net.m0;
    int step = 0;
    print_step(net, step, "INIT", m);
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::istringstream ss(line);
        std::string tok;
        ss >> tok;
        if (!tok.empty() && (std::isdigit(static_cast<unsigned char>(tok[0])) || tok[0] == '-')) ss >> tok;  // drop time stamp
        if (tok == "END") continue;
        ++step;
        if (tok == "FIRE") {
            std::string name;
            ss >> name;
            auto it = net.transition_index.find(name);
            if (it == net.transition_index.end() || !net.enabled(m, it->second)) {
                std::cout << "ERROR|" << step << "|" << name << "|not enabled\n";
                return 2;
            }
            net.fire(m, it->second);
            print_step(net, step, "FIRE " + name, m);
        } else if (tok == "ARRIVE") {
            std::string pn;
            int n;
            ss >> pn >> n;
            m[net.place_index.at(pn)] += n;
            print_step(net, step, "ARRIVE " + pn + " " + std::to_string(n), m);
        } else {
            std::cerr << "bad trace line: " << line << "\n";
            return 1;
        }
    }
    return 0;
}

// Peak resident set size of THIS process in kB.  On Linux we read VmHWM from /proc/self/status:
// getrusage(ru_maxrss) is inherited across fork+exec and would report the launching process's peak.
static long peak_rss_kb() {
#ifdef __linux__
    std::ifstream f("/proc/self/status");
    std::string line;
    while (std::getline(f, line))
        if (line.rfind("VmHWM:", 0) == 0) return std::atol(line.c_str() + 6);
#endif
#if defined(__unix__) || defined(__APPLE__)
    struct rusage ru;
    getrusage(RUSAGE_SELF, &ru);
#ifdef __APPLE__
    return ru.ru_maxrss / 1024;  // bytes on macOS
#else
    return ru.ru_maxrss;         // kilobytes on other unixes
#endif
#else
    return -1;
#endif
}

static int cmd_bench(const Net& net, const std::string& scen_path, int reps) {
    using clk = std::chrono::steady_clock;
    Scenario sc = Scenario::load(net, scen_path);
    Simulator sim(net, sc);
    // warm-up
    for (int i = 0; i < 50; ++i) sim.run();
    // (a) whole-run cost without per-step instrumentation
    int64_t fired = 0;
    auto t0 = clk::now();
    for (int i = 0; i < reps; ++i) fired = sim.run().fired;
    auto t1 = clk::now();
    const double run_ns = std::chrono::duration<double, std::nano>(t1 - t0).count() / reps;
    // Peak RSS of the controller itself (binary + C++ runtime + model + one simulation), measured
    // BEFORE the latency-sample buffer below is allocated.
    const long rss_controller_kb = peak_rss_kb();
    // (b) per event-time-step latency distribution (includes ~2 clock reads of overhead)
    std::vector<int64_t> steps;
    const int reps_b = std::min(reps, 20000);
    steps.reserve(static_cast<size_t>(reps_b) * 32);
    for (int i = 0; i < reps_b; ++i) sim.run(nullptr, &steps);
    std::sort(steps.begin(), steps.end());
    auto pct = [&](double q) { return steps[std::min(steps.size() - 1, static_cast<size_t>(q * steps.size()))]; };
    const double mean = std::accumulate(steps.begin(), steps.end(), 0.0) / steps.size();
    std::printf("{\"reps\": %d, \"transition_firings_per_run\": %lld, \"mean_run_ns\": %.1f, "
                "\"mean_ns_per_firing\": %.2f, \"steps_per_run\": %zu, "
                "\"step_ns_mean\": %.1f, \"step_ns_p50\": %lld, \"step_ns_p99\": %lld, \"step_ns_max\": %lld, "
                "\"model_bytes\": %zu, \"peak_rss_kb\": %ld, \"peak_rss_with_latency_buffer_kb\": %ld}\n",
                reps, static_cast<long long>(fired), run_ns, run_ns / std::max<int64_t>(1, fired),
                steps.size() / static_cast<size_t>(reps_b), mean,
                static_cast<long long>(pct(0.50)), static_cast<long long>(pct(0.99)),
                static_cast<long long>(steps.back()), net.model_bytes(), rss_controller_kb, peak_rss_kb());
    return 0;
}

int main(int argc, char** argv) {
    try {
        if (argc >= 4) {
            const std::string mode = argv[1];
            Net net = Net::load(argv[2]);
            if (mode == "simulate") return cmd_simulate(net, argv[3]);
            if (mode == "replay") return cmd_replay(net, argv[3]);
            if (mode == "bench" && argc >= 5) return cmd_bench(net, argv[3], std::atoi(argv[4]));
        }
        std::cerr << "usage:\n  petri_engine simulate <net> <scenario>\n"
                     "  petri_engine replay   <net> <trace>\n"
                     "  petri_engine bench    <net> <scenario> <reps>\n";
        return 1;
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
}
