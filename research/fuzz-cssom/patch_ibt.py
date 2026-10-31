import io

p = "/home/<user>/wk/WebKit/Source/WebCore/bindings/js/SerializedScriptValue.cpp"
s = io.open(p, encoding="utf-8").read()

old = """        if (!indexSuccessfullyRead || index >= m_backingStores.size()) {
            fail();
            return JSValue();
        }

        if (!m_imageBitmaps[index]) {"""

new = """        if (!indexSuccessfullyRead || index >= m_backingStores.size()) {
            fail();
            return JSValue();
        }
        {
            auto* q = reinterpret_cast<unsigned char*>(&m_backingStores.at(index));
            fprintf(stderr, "[IBT] sizeof=%zu size=%zu cap=%zu idx=%u elem=%p bytes=",
                sizeof(std::optional<ImageBitmapBacking>), m_backingStores.size(),
                m_backingStores.capacity(), index, static_cast<void*>(q));
            for (unsigned b = 0; b < 40; ++b) fprintf(stderr, "%02x", q[b]);
            fprintf(stderr, "\\n");
        }

        if (!m_imageBitmaps[index]) {"""

assert s.count(old) == 1, s.count(old)
s = s.replace(old, new)

if "#include <stdio.h>" not in s:
    s = s.replace('#include "config.h"', '#include "config.h"\n#include <stdio.h>', 1)

io.open(p, "w", encoding="utf-8").write(s)
print("patched")
