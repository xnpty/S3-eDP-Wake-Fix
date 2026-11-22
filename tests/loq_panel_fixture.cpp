#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>

using UInt8 = uint8_t;
using UInt32 = uint32_t;
using UInt64 = uint64_t;
using IOReturn = int;
constexpr int kIOReturnSuccess = 0, kIOReturnNoMemory = -1;
int trueValue;
int *kOSBooleanTrue = &trueValue;
bool deepIdle, enabled = true, refuseMux, lcdAvailable = true;
UInt32 muxPad = 0x10002, resetPad = 0x10003, mode = 2, route = 2, reset = 2;
int muxWrites, resetWrites;

struct OSObject {
    UInt32 value = 0;
    void release() { delete this; }
};
struct OSNumber {
    static OSObject *withNumber(UInt32 n, int) { return new OSObject{n}; }
};
struct IORegistryEntry {
    static IORegistryEntry *fromPath(const char *);
    virtual ~IORegistryEntry() = default;
    void release() {}
};
struct IOACPIPlatformDevice : IORegistryEntry {
    int evaluateInteger(const char *name, UInt64 *out) {
        assert(!strcmp(name, "_ADR"));
        *out = 0xffffffff8000a450;
        return 0;
    }
    int evaluateInteger(const char *name, UInt32 *out, OSObject **param = nullptr, int = 0) {
        if (!strcmp(name, "DMMP")) *out = muxPad;
        else if (!strcmp(name, "DLRP")) *out = resetPad;
        else if (!strcmp(name, "MXDM")) { assert(!(*param)->value); *out = mode; }
        else if (!strcmp(name, "LRST")) { assert(!(*param)->value); *out = reset; }
        else if (!strcmp(name, "MXDS")) {
            if ((*param)->value) {
                assert((*param)->value == 0x11);
                ++muxWrites;
                if (refuseMux) return -2;
                route = 2;
                *out = 1;
            } else {
                *out = route;
            }
        } else return -2;
        return 0;
    }
    int evaluateObject(const char *name, void *, OSObject **param, int) {
        assert(!strcmp(name, "LRST"));
        assert((*param)->value == 1 || (*param)->value == 2);
        ++resetWrites;
        reset = (*param)->value;
        return 0;
    }
};
IORegistryEntry *IORegistryEntry::fromPath(const char *path) {
    static IOACPIPlatformDevice gpu, lcd;
    if (strstr(path, "LCD0")) return lcdAvailable ? &lcd : nullptr;
    return &gpu;
}
#define OSDynamicCast(type, object) dynamic_cast<type*>(object)
#define OSSafeReleaseNULL(entry) if (entry) { entry->release(); entry = nullptr; }
#define LOG(...) do {} while (0)
bool PE_parse_boot_argn(const char *, UInt32 *value, unsigned) {
    *value = enabled;
    return enabled;
}
struct PCIFixture {
    UInt32 identified = 0x28e110de;
    UInt32 configRead32(int off) {
        return off == 0 ? identified : 0x3d0617aa;
    }
} pci;
struct RootFixture {
    int *getProperty(const char *) { return deepIdle ? kOSBooleanTrue : nullptr; }
} root;
// LOQ_PANEL_STATE

struct NVRM {
    LoqPanelState fLoqPanelState;
    PCIFixture *fPCI = &pci;
    RootFixture *getPMRootDomain() { return &root; }
    void saveLoqPanelState();
    void restoreLoqPanelState();
};
// LOQ_PANEL_IMPLEMENTATION

int main() {
    NVRM d;
    d.saveLoqPanelState();
    route = reset = 1;
    d.restoreLoqPanelState();
    assert(muxWrites == 1 && resetWrites == 1 && route == 2 && reset == 2);
    d.restoreLoqPanelState();
    assert(muxWrites == 1 && resetWrites == 1);

    d.saveLoqPanelState();
    route = reset = 1;
    mode = 4;
    d.restoreLoqPanelState();
    assert(muxWrites == 1 && resetWrites == 1);

    route = mode = reset = 2;
    d.saveLoqPanelState();
    route = reset = 1;
    refuseMux = true;
    d.restoreLoqPanelState();
    assert(muxWrites == 2 && resetWrites == 1 && route == 1);
    refuseMux = false;

    route = reset = 2;
    d.saveLoqPanelState();
    route = 1;
    ++muxPad;
    d.restoreLoqPanelState();
    assert(muxWrites == 2 && resetWrites == 1);

    route = reset = 2;
    resetPad = muxPad;
    d.saveLoqPanelState();
    reset = 1;
    d.restoreLoqPanelState();
    assert(muxWrites == 2 && resetWrites == 1);

    resetPad = 0x10003;
    route = 2;
    reset = 1;
    d.saveLoqPanelState();
    reset = 2;
    d.restoreLoqPanelState();
    assert(muxWrites == 2 && resetWrites == 1 && reset == 2);

    deepIdle = true;
    d.saveLoqPanelState();
    assert(d.fLoqPanelState.route == 0);
    deepIdle = false;
    pci.identified = 0;
    d.saveLoqPanelState();
    assert(d.fLoqPanelState.route == 0);
    pci.identified = 0x28e110de;
    enabled = false;
    d.saveLoqPanelState();
    assert(d.fLoqPanelState.route == 0);
    enabled = true;
    lcdAvailable = false;
    d.saveLoqPanelState();
    assert(d.fLoqPanelState.route == 0);
    lcdAvailable = true;
    muxPad = 0xc0001;
    d.saveLoqPanelState();
    assert(d.fLoqPanelState.route == 0);
    muxPad = 0x10017;
    d.saveLoqPanelState();
    assert(d.fLoqPanelState.route == 0);
    puts("LOQ eDP state restore passed all 12 cases");
}
