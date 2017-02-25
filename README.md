# staticwebsync

staticwebsync is a command-line tool for automating the fiddly aspects of hosting your static web site on Amazon S3 or CloudFront. It automates the process of configuring the services for hosting web sites, and synchronizes the contents of a local folder to the site.

**Contents**

* [Installation](#installation)
* [Quick start](#quickstart)
* [Why would I want to host my web site on S3/CloudFront?](#whys3cf)
* [Why would I want to use staticwebsync to set it up?](#whysws)
* [Why wouldn't I want to host my web site on S3/CloudFront?](#whynots3cf)
* [How to use staticwebsync](#howto)
* [Contributing](#contributing)
* [Copyright and license](#copyright)

### <a name="installation"></a>Installation

staticwebsync is built using Python and so it is installed using Python's package manager _pip_.

First install Python from [python.org](https://www.python.org/downloads/) if you don't have it already. staticwebsync needs at least version 3, and versions 3.4 and later include _pip_ which means you don't have to download it separately.

**Mac / Linux**: In a terminal run:

```sh
# change to your home directory:
cd
# set up a directory to install staticwebsync into by giving a new directory name
# to venv:
python3 -m venv staticwebsync
# install staticwebsync and its dependencies:
staticwebsync/bin/pip install staticwebsync
# (optional) put a link in your path so that you can run it just by typing sws:
sudo ln -s `pwd`/staticwebsync/bin/sws /usr/local/bin/
```

**Windows**: In a Command Prompt window run:
```
REM change to your home directory:
cd %HOMEPATH%
REM set up a directory to install staticwebsync into by giving a new directory
REM name to venv:
py -3 -m venv staticwebsync
REM install staticwebsync and its dependencies:
staticwebsync\Scripts\pip install staticwebsync
REM (optional) put %HOMEPATH%\staticwebsync\Scripts in your PATH so that you can
REM run it just by typing sws
```

### <a name="quickstart"></a>Quick start

If you haven't already done so then sign up for Amazon's [S3](http://aws.amazon.com/s3/) and [CloudFront](http://aws.amazon.com/cloudfront/) services.

staticwebsync needs your Amazon Web Services credentials (your Access Key ID and Secret Access Key) to access your account. You can find them in the [Security Credentials section of the AWS site](https://console.aws.amazon.com/iam/home?#security_credential). You can either specify them on the command-line every time you run staticwebsync (`--access-key-id YOURACCESSKEY --secret-access-key YOURSECRETACCESSKEY`), or store them in a .aws/credentials file. The latter option is nice because that file is also used by other tools so you can just set them up once instead of setting them up for each tool you use. See the [AWS Command Line Interface documentation](http://docs.aws.amazon.com/cli/latest/userguide/cli-chap-getting-started.html) for info about setting up the credentials file.

To configure the services and sync your site for the first time run the tool like this:

```sh
sws www.example.com yourlocalfolder
```

and then look at the end of the output for a message telling you how to set up your DNS entry for the site. Google has some good [instructions about setting up CNAME DNS records using various domain registrars](https://support.google.com/a/topic/1615038). If you want your web site to use a "bare" domain like "example.com" without a "www." prefix then that only works if you're using Route 53 as your DNS host (you have to use Route 53's special ALIAS record type rather than CNAME records, because CNAME records don't work for the root of a domain).

For information about other options run the tool with the `--help` argument.

### <a name="whys3cf"></a>Why would I want to host my web site on S3/CloudFront?

Hosting a site using S3 and CloudFront has some distinct advantages over traditional hosting on a shared or dedicated server:

* **Scalability** S3 and CloudFront can support web sites of any size and popularity, so they can handle even severe spikes of traffic.
* **Speed** CloudFront is a CDN (Content Delivery Network) that caches the contents of your site in numerous servers located all around the world, and users' incoming requests are automagically routed to a server near them so it's very fast.
* **Pay-for-what-you-use pricing with no minimums** Web hosting companies often offer cheap hosting deals with "unlimited" bandwidth and storage, but where "unlimited" is actually defined in the small print as something like "as much as you can use on one server with a small hard drive and network connection". S3/CloudFront [charge by the gigabyte](http://aws.amazon.com/s3/pricing/) for the storage and bandwidth that you actually use.
* **Reliability** Amazon S3 has a [99.9% uptime service level agreement](http://aws.amazon.com/s3/sla/).

### <a name="whysws"></a>Why would I want to use staticwebsync to set it up?
Configuring S3 and CloudFront for web site hosting requires a number of steps that have to be done manually when using other tools, and synchronizing new/changed files also requires effort to get right. The goal of staticwebsync is that you should be able to use it without having to know anything about the details of how S3 and CloudFront work. You simply use a command like:

`sws www.example.com yourlocalfolder`

and that will sync the contents of yourlocalfolder to S3 and CloudFront, automating all of the following:

* creating a S3 bucket for the site if one doesn't already exist
* configuring the security policy and website access properties of the bucket
* creating a CloudFront distribution if needed, and configuring it to use the S3 bucket as its origin
* uploading your local files to the bucket and setting their security policy
* setting the Internet media types (MIME types) of the uploaded files based on their filename extensions
* skipping files that already exist in the bucket and haven't changed (by comparing the MD5 hashes of the local and remote files)
* skipping local files and folders that begin with a dot, such as those used by version control systems like Git or Subversion
* deleting files in the bucket that no longer exist locally
* sending CloudFront cache invalidation messages for any changed files so that they are updated in the CDN servers as soon as possible

### <a name="whynots3cf"></a>Why wouldn't I want to host my web site on S3/CloudFront?

* As the name suggests, staticwebsync is only for _static_ sites, that is, sites that are just a bunch of ordinary HTML files (and images and Javascript etc.), so it doesn't work with anything that needs server-side scripting, such as PHP. That means that it can't be used out-of-the-box with blogging/CMS systems like Wordpress.
* S3 doesn't currently support using HTTPS (SSL) transfers for web site hosting, so you shouldn't use it for web sites with private data. The way staticwebsync configures things, if you use CloudFront then you can use HTTPS for accessing your site through the ".cloudfront.net" domain, but that is misleading because the data is still transferred from S3 to CloudFront using a regular unencrypted HTTP connection so it doesn't provide full security (for anyone interested: we have to use the http-only CloudFront origin policy because the S3 website endpoints don't currently support HTTPS).

### <a name="howto"></a>How to use staticwebsync

See the Quick Start example above, and use the `--help` option for information about more options.

### <a name="contributing"></a>Contributing

Please post bug reports and feature requests in the [issues section on GitHub](https://github.com/staticwebsync/staticwebsync/issues), and patches (especially in the form of GitHub pull requests) are very welcome of course. I can be contacted at: staticwebsync at jjc1138 dot net

### <a name="copyright"></a>Copyright

staticwebsync is copyright © 2011-2016 Jon Colverson and licensed under the [MIT License](https://opensource.org/licenses/MIT)
