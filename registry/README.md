# NiFi Registry - quản lý phiên bản flow (Flow Lifecycle)

Vì sao cần Registry? Trong thực tế, flow NiFi **không được lưu trong Git một
cách tự nhiên**: canvas flow là state của NiFi server. NiFi Registry giải
quyết bằng cách lưu **phiên bản có đánh số (v1, v2, v3...)** của mỗi process
group, cho phép:

- **Rollback** về phiên bản trước khi chỉnh sửa gây lỗi
- **Promotion** dev → test → prod bằng cách import đúng phiên bản đã duyệt
- **Kiểm toán** — ai commit phiên bản nào, khi nào, ghi chú gì

Đây là cơ chế "source of truth" thật; file `flows/0*.json` trong repo chỉ là
bản snapshot dùng để **import lần đầu** (bootstrap) và cho CI.

## Các bước versioning trên môi trường này

```bash
# 0. Tạo bucket trong Registry (chạy 1 lần)
bash registry/bootstrap_registry.sh
```

1. **Kết nối NiFi → Registry** (làm 1 lần): menu toàn cục (☰) →
   *Registry Clients* → **+ ADD REGISTRY CLIENT**:
   - Name: `local-registry`
   - URL: `http://nifi-registry:18080` — hostname nội bộ docker network,
     *không* dùng localhost vì NiFi container phải trỏ tới container khác.

2. **Đưa flow dưới sự kiểm soát phiên bản**: click phải process group
   (ví dụ `MQTT-INGEST`) → *Versioning* → **Start version control** →
   chọn `local-registry` / bucket `iot-datahub` / đặt FlowName → Save.

3. **Commit thay đổi**: sau mỗi lần chỉnh sửa canvas, biểu tượng phiên bản
   hiện dấu chấm đỏ → click phải → *Versioning* → **Save flow versions** →
   tăng version, ghi commit message.

4. **Rollback**: click phải → *Versioning* → **Change version** → chọn
   phiên bản cũ hơn.

5. **Promotion**: môi trường khác (VD máy chấm điểm/GVHD) chỉ cần NiFi +
   Registry client trỏ cùng bucket → kéo phiên bản X vào canvas → Import.

## Tương tác với CI

Workflow `ci/workflows/nifi-flow-ci.yml` minh hoạ đường promotion kiểu
phổ biến nhất trong doanh nghiệp: **Registry là nguồn chân lý**, script
`flows/import_flows.py` là phương tiện vận chuyển (transport) — CI chỉ
gọi lại script này với secret của môi trường đích.
