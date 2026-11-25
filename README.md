# ☁️ Bulut Bilişim Dersi Laboratuvar Uygulama Föyü: Mini Drive

Bu laboratuvar çalışmasında; modern bulut mimarilerini kullanarak **1 saat içinde** sunucusuz (serverless) bir dosya yönetim (**Mini Drive**) web uygulamasını Azure üzerinde ayağa kaldıracaksınız.

---

## 🎯 Laboratuvar Hedefleri
Bu uygulamayı tamamladığınızda şunları deneyimlemiş olacaksınız:
1. **Azure Blob Storage:** Dosyaları nesne depolama (Object Storage) alanında saklama ve güvenli erişim.
2. **Azure Container Registry (ACR):** Özel bir konteyner kayıt defteri oluşturma ve imaj yönetimi.
3. **Azure Container Instances (ACI):** Sanal makine kurmadan saniyeler içinde sunucusuz Docker konteyneri çalıştırma.
4. **Ortam Değişkenleri (Environment Variables):** Bağlantı dizesini (`Connection String`) koda gömmeden bulut ortamında yönetme.

---

## 🏗️ Mimari Şema

```text
  [ Kullanıcı Tarayıcısı ]
            │ HTTP (Port 80)
            ▼
┌───────────────────────────────────────────┐
│       Azure Container Instances (ACI)     │
│  ┌─────────────────────────────────────┐  │
│  │   Python 3.11 + Flask + Gunicorn    │  │
│  │          "Mini Drive App"           │  │
│  └──────────────────┬──────────────────┘  │
└─────────────────────┼─────────────────────┘
                      │ Azure SDK / Stream
                      ▼
┌───────────────────────────────────────────┐
│            Azure Blob Storage             │
│  ┌─────────────────────────────────────┐  │
│  │     Container: "drive" (Private)    │  │
│  │     - dosya1.pdf                    │  │
│  │     - rapor.docx                    │  │
│  └─────────────────────────────────────┘  │
└───────────────────────────────────────────┘
```

> **📌 Backend Proxy Güvenliği:** Azure Blob Storage varsayılan olarak **Private (Özel)** erişim seviyesindedir. Uygulamamız dosyaları Azure'dan okuyup istemciye stream ederek indirdiği için Storage Account'u dış dünyaya anonim erişime açmanıza gerek kalmaz.

---

## ⚠️ Azure for Students Abonelikleri İçin Önemli Bilgilendirme

Microsoft, öğrenci aboneliklerinde sınıf içi uygulamaları etkileyebilecek iki güvenlik/kaynak kısıtı uygulamaktadır:
1. **Bölge Kısıtlaması (`RequestDisallowedByAzure`):** Öğrenci aboneliklerinde `westeurope` gibi bazı bölgeler kapalı olabilir. Aşağıdaki yönergelerde izinli bölge komut satırından otomatik tespit edilmektedir (varsayılan: `westus3`).
2. **Bulut Derleme Kısıtlaması (`TasksOperationsNotAllowed`):** Microsoft, öğrenci hesaplarında `az acr build` (ACR Tasks) sunucularını kapatmıştır. Bu nedenle derste imajı doğrudan kendi ACR'nize kopyalamak için **`az acr import`** komutunu kullanacağız (10 saniyede tamamlanır).

---

## ⏱️ Adım Adım Laboratuvar Uygulaması (Süre: 45 - 60 Dakika)

Komutları doğrudan **Azure Cloud Shell (Bash)** veya bilgisayarınızdaki **Azure CLI** terminalinde çalıştırabilirsiniz.

---

### Adım 1: Hazırlık ve İzinli Bölgeyi Belirleme

Cloud Shell terminalini açın ve gerekli Azure servis sağlayıcılarını etkinleştirin:

```bash
# 1. Gerekli servis sağlayıcılarını kaydedin
az provider register --namespace Microsoft.ContainerRegistry
az provider register --namespace Microsoft.ContainerInstance

# 2. Aboneliğinizin izin verdiği ilk bölgeyi otomatik bulun (bulamazsa westus3 kullanır)
MY_LOCATION=$(az policy assignment list --query "[?parameters.listOfAllowedLocations].parameters.listOfAllowedLocations.value[0]" -o tsv | head -n 1 | tr -d '\r')
MY_LOCATION=${MY_LOCATION:-westus3}

echo "✅ Kullanılacak bölge: $MY_LOCATION"
```

---

### Adım 2: Resource Group ve Storage Account Oluşturma

Tüm servislerimizi laboratuvar sonunda tek komutla temizleyebilmek için tek bir Resource Group altında topluyoruz:

```bash
# Değişkenleri tanımlayın
MY_RG="rg-bulutlab-$RANDOM"
MY_STORAGE="stdrive$RANDOM"
MY_ACR="acrdrive$RANDOM"

# 1. Resource Group oluşturun
az group create --name $MY_RG --location $MY_LOCATION

# 2. Storage Account oluşturun
az storage account create \
  --name $MY_STORAGE \
  --resource-group $MY_RG \
  --location $MY_LOCATION \
  --sku Standard_LRS \
  --kind StorageV2

# 3. Connection String değerini alıp değişkene kaydedin
CONN_STR=$(az storage account show-connection-string \
  --name $MY_STORAGE \
  --resource-group $MY_RG \
  --query connectionString \
  --output tsv)

echo "✅ Storage Account hazır: $MY_STORAGE"
```

*(Not: `drive` adındaki container'ı elle açmanıza gerek yoktur; uygulama ilk çalıştığında yoksa otomatik oluşturur.)*

---

### Adım 3: Azure Container Registry (ACR) Oluşturma ve İmajı Aktarma

Özel kayıt defterinizi oluşturun ve hazır `linux/amd64` uyumlu imajı ACR Tasks kısıtlamasına takılmadan tek satırda kendi deponuza aktarın:

```bash
# 1. ACR oluşturun (--admin-enabled true zorunludur)
az acr create \
  --resource-group $MY_RG \
  --name $MY_ACR \
  --sku Basic \
  --admin-enabled true

# 2. İmajı kendi ACR'nize kopyalayın (az acr import)
az acr import \
  --name $MY_ACR \
  --source ghcr.io/bkaynar/bulut-11:v1 \
  --image mini-drive:v1

echo "✅ İmaj ACR içine aktarıldı!"
```

*(İsteğe Bağlı Doğrulama: `az acr repository list --name $MY_ACR -o table` komutuyla imajın geldiğini görebilirsiniz.)*

---

### Adım 4: Azure Container Instances (ACI) ile Yayınlama

Kendi ACR'nizdeki imajı sunucusuz container olarak 80 portundan ayağa kaldırın:

```bash
# 1. ACR giriş bilgilerini alın
ACR_LOGIN_SERVER=$(az acr show --name $MY_ACR --query loginServer --output tsv)
ACR_PASSWORD=$(az acr credential show --name $MY_ACR --query "passwords[0].value" --output tsv)
DNS_LABEL="mini-drive-$RANDOM"

# 2. Container'ı başlatın
az container create \
  --resource-group $MY_RG \
  --name mini-drive-app \
  --image ${ACR_LOGIN_SERVER}/mini-drive:v1 \
  --registry-login-server $ACR_LOGIN_SERVER \
  --registry-username $MY_ACR \
  --registry-password "$ACR_PASSWORD" \
  --dns-name-label $DNS_LABEL \
  --ports 80 \
  --cpu 1 \
  --memory 1 \
  --environment-variables \
      AZURE_STORAGE_CONNECTION_STRING="$CONN_STR" \
      CONTAINER_NAME="drive" \
      PORT="80"

# 3. Uygulamanın web adresini ekrana yazdırın
echo "🚀 UYGULAMANIZ HAZIR!"
echo "Adres: http://$(az container show --resource-group $MY_RG --name mini-drive-app --query ipAddress.fqdn -o tsv)"
```

---

### Adım 5: Uygulamayı Test Etme

1. Ekrana basılan `http://mini-drive-XXXXX.<bolge>.azurecontainer.io` adresini tarayıcınızda açın.
2. **Yapılacak Testler:**
   - 📂 **Yükleme:** Bilgisayarınızdan bir PDF veya görsel dosyasını sürükleyip bırakarak yükleyin.
   - 📥 **İndirme:** Dosyayı başarıyla geri indirin.
   - 🗑️ **Silme:** Dosyayı silin ve anlık liste güncellemesini gözlemleyin.
   - 🩺 **Health Check:** `http://<ADRES>/health` yolunu açıp `{"status": "ok"}` çıktısını doğrulayın.
3. **Portal Doğrulaması:** Azure Portal'da Storage Account'unuza girip **Containers** sekmesinde `drive` klasörünü ve yüklediğiniz dosyaları inceleyin.

---

### Adım 6: Temizlik (Clean Up) - 🚨 KREDİ KORUMA ADIMI

Ders sonunda öğrenci kredinizin tükenmemesi için oluşturduğunuz tüm kaynakları tek komutla silin:

```bash
az group delete --name $MY_RG --yes --no-wait
```

---

## 🛠️ Alternatif Yöntem: GitHub Actions ile Derleme

Kodu kendi GitHub hesabınızda derleyip doğrudan ACR'ye göndermek isterseniz:
1. Bu repoyu (`https://github.com/bkaynar/bulut-11`) kendi GitHub hesabınıza **Fork** edin.
2. GitHub reponuzda **Settings &rarr; Secrets and variables &rarr; Actions** bölümüne gidin.
3. İki adet Secret tanımlayın:
   - `ACR_NAME`: Azure Container Registry adınız (örn: `acrdrive12345`)
   - `ACR_PASSWORD`: ACR parolanız (`az acr credential show` çıktısı)
4. **Actions** sekmesinden `Build and Push to Azure Container Registry (ACR)` iş akışını çalıştırın. GitHub, imajı `linux/amd64` mimarisinde derleyip doğrudan sizin ACR'nize gönderecektir.

---

## 💻 Yerel Geliştirme (Local Development)

```bash
# Sanal ortam kurma
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Bağımlılıkları yükleme
pip install -r requirements.txt

# Çevre değişkenlerini ayarlama
cp .env.example .env
# .env içine AZURE_STORAGE_CONNECTION_STRING değerinizi yazın

# Çalıştırma
python app.py
```
Tarayıcıdan `http://localhost:80` adresinden erişebilirsiniz.
