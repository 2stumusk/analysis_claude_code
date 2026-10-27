// One line of the USB serial protocol, daemon -> device.
//
// {"v":1,"t":<unix>,"tz":<utc offset s>,"f":<focus index>,
//  "a":[{"id","l"(label),"b"(abbr),"s"(state),"d"(detail),"c"(cwd),
//        "e"(task s),"n"(tools),"k"(sessions),"x"(alert 0/1)}...],
//  "p":{"lv","xi","xs","en","md","tk","tl","er","lu","fd"},
//  "u":{"o"(output tokens),"t"(total)} | null}
//
// Device -> daemon lines are {"hello":"deskpet",...} and {"btn":"B"}.
#pragma once

#include "model.h"

namespace pet {

// Parse `line` into `m`. On failure `m` is left untouched and false returned.
bool parseFrame(const char* line, Model& m, float now);

}  // namespace pet
