// Place/transition Petri net loaded from the plain-text format written by
// petri/net.py (PetriNet.to_text).  Header-only, C++17, no dependencies.
//
//   place <name> <initial tokens>
//   transition <name> <controllable 0|1> <delay ticks>   (file order = dispatch priority)
//   pre|post <transition> <place> <weight>
//   (lines starting with '#' are comments)
#pragma once
#include <cstdint>
#include <fstream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace petri {

using Marking = std::vector<int32_t>;

struct Arc {
    int place;
    int32_t weight;
};

struct Transition {
    std::string name;
    bool controllable = false;
    int64_t delay = 0;        // ticks; 0 = immediate
    std::vector<Arc> pre;     // enabling condition: m[place] >= weight
    std::vector<Arc> delta;   // firing effect:      m[place] += weight (post - pre, non-zero only)
};

class Net {
public:
    std::vector<std::string> places;
    Marking m0;
    std::vector<Transition> transitions;
    std::unordered_map<std::string, int> place_index;
    std::unordered_map<std::string, int> transition_index;

    static Net load(const std::string& path) {
        std::ifstream in(path);
        if (!in) throw std::runtime_error("cannot open net file: " + path);
        Net net;
        std::vector<std::map<int, int32_t>> pre, post;
        std::string line;
        while (std::getline(in, line)) {
            if (line.empty() || line[0] == '#') continue;
            std::istringstream ss(line);
            std::string kw;
            ss >> kw;
            if (kw == "place") {
                std::string name;
                int tokens;
                ss >> name >> tokens;
                net.place_index[name] = static_cast<int>(net.places.size());
                net.places.push_back(name);
                net.m0.push_back(tokens);
            } else if (kw == "transition") {
                Transition t;
                int ctl;
                ss >> t.name >> ctl >> t.delay;
                t.controllable = ctl != 0;
                net.transition_index[t.name] = static_cast<int>(net.transitions.size());
                net.transitions.push_back(t);
                pre.emplace_back();
                post.emplace_back();
            } else if (kw == "pre" || kw == "post") {
                std::string tn, pn;
                int32_t w;
                ss >> tn >> pn >> w;
                auto ti = net.transition_index.find(tn);
                auto pi = net.place_index.find(pn);
                if (ti == net.transition_index.end() || pi == net.place_index.end())
                    throw std::runtime_error("bad arc: " + line);
                (kw == "pre" ? pre : post)[ti->second][pi->second] += w;
            } else {
                throw std::runtime_error("unknown keyword in net file: " + kw);
            }
        }
        for (size_t t = 0; t < net.transitions.size(); ++t) {
            std::map<int, int32_t> d;
            for (auto& [p, w] : pre[t]) {
                net.transitions[t].pre.push_back({p, w});
                d[p] -= w;
            }
            for (auto& [p, w] : post[t]) d[p] += w;
            for (auto& [p, w] : d)
                if (w != 0) net.transitions[t].delta.push_back({p, w});
        }
        return net;
    }

    bool enabled(const Marking& m, int t) const {
        for (const Arc& a : transitions[t].pre)
            if (m[a.place] < a.weight) return false;
        return true;
    }

    void fire(Marking& m, int t) const {
        for (const Arc& a : transitions[t].delta) m[a.place] += a.weight;
    }

    // Approximate static memory held by the model (bytes), for the resource report.
    size_t model_bytes() const {
        size_t b = sizeof(*this) + m0.capacity() * sizeof(int32_t);
        for (const auto& p : places) b += sizeof(p) + p.capacity();
        for (const auto& t : transitions)
            b += sizeof(t) + t.name.capacity() + (t.pre.capacity() + t.delta.capacity()) * sizeof(Arc);
        return b;
    }
};

}  // namespace petri
