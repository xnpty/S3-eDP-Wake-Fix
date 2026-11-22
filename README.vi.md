# Bản vá màn hình khi LOQ thức từ S3

[Tải v0.1.0](https://github.com/xnpty/LOQ-S3-eDP-Fix/releases/tag/v0.1.0) · [English](README.md)

Trên máy thử nghiệm, khi thức từ S3, firmware chuyển tuyến eDP sang iGPU dù BIOS đang ở chế độ chỉ dùng GPU rời. NVRM khôi phục tuyến về RTX 4050 trước khi driver tiếp tục khởi tạo màn hình.

## Yêu cầu

- Lenovo LOQ 15IAX9 (83GS), RTX 4050 Laptop `10de:28e1`, subsystem Lenovo `17aa:3d06` và màn hình trong nối với RTX ở chế độ GPU rời. BIOS đã thử là `NECN53WW`.
- Firmware và OpenCore đã có **ACPI S3**. Có thể kiểm tra bằng log `ACPI S3 WAKE` từ lần ngủ trước. Nếu dùng Windows song song thì chạy `powercfg /a` để xem có Standby (S3) hay không.
- macOS Tahoe trên Intel, đã cài và chạy được bộ driver HighDelay `v3.0.2-nvk`. Đã thử trên Tahoe 26.7.1 (25G241) và OpenCore 1.0.9. [Driver gốc](https://github.com/HighDelay/nvidia-macos-driver-nvk/releases/tag/v3.0.2-nvk)
- Python 3.9 trở lên và quyền quản trị. Lệnh bên dưới dùng `/usr/bin/python3` khi máy đã cài Command Line Tools hoặc Xcode.

## Cài đặt

1. Tải ZIP và `SHA256SUMS` ở cùng một release. Chạy các lệnh từ thư mục tải xuống.

   ```sh
   shasum -a 256 -c SHA256SUMS
   ditto -x -k LOQ-S3-eDP-Fix-0.1.0.zip .
   cd LOQ-S3-eDP-Fix-0.1.0
   /usr/bin/python3 install.py check
   sudo /usr/bin/python3 install.py install
   ```

   Lưu đường dẫn bản sao mà bộ cài in ra để có thể hoàn tác kext và AuxKC.

2. Sao lưu đúng `EFI/OC/config.plist` đang dùng. Thêm `nvrmloqs3=1` vào cuối chuỗi boot-args hiện có trong `NVRAM → Add → 7C436110-AB2A-4BBB-A880-FE41995C9F82`. Đặt `boot-args` trong mục `NVRAM → Delete` của cùng GUID để OpenCore nạp chuỗi mới. Nếu trước đây bạn đã thêm riêng SSDT bật Deep Idle thì vô hiệu mục SSDT đó trong cấu hình dùng S3. Kiểm tra plist bằng `ocvalidate` đúng phiên bản OpenCore.

3. Khởi động lại một lần. Lưu công việc, chọn Sleep, rồi đánh thức bằng nút nguồn hoặc mở nắp. Xác nhận màn hình trong lên và kiểm tra log.

   ```sh
   log show --last 15m --style compact --predicate 'process == "kernel" AND (eventMessage CONTAINS "ACPI S3 WAKE" OR eventMessage CONTAINS "LOQ S3 eDP")'
   ```

Máy thử nghiệm ở S3 khoảng **75 giây** khi tháo chuột và bàn phím USB, thức theo hẹn giờ và khôi phục eDP 1080p 144 Hz. Khi cắm cả hai thiết bị, máy vẫn có lần thức nền sớm qua `XDCI CNVW`. Màn hình trong vẫn lên khi thức hẳn.

## Hoàn tác

Chạy lệnh với đúng thư mục sao lưu mà bộ cài đã in ra.

```sh
sudo /usr/bin/python3 install.py rollback '/Library/NullMoth/LOQ-S3-eDP-THAY-BANG-THU-MUC-CUA-BAN'
```

Khôi phục plist OpenCore đã sao lưu hoặc bỏ `nvrmloqs3=1` trong boot-args, sau đó khởi động lại. Khi báo lỗi, ghi model, phiên bản BIOS, build macOS, tag driver gốc, UUID kext và các dòng log S3 liên quan.

Tài (xnpty) kiểm thử trên LOQ và duy trì bản này. Driver macOS gốc của NullMoth Systems, bản nền NVK của HighDelay và mã kernel GPU của NVIDIA. [Giấy phép](LICENSE) · [Nguồn và ghi công](README.md#source-and-credits)
