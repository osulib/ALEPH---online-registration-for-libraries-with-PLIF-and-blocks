### ALEPH Online registration - for libraries with PLIF and using patron global blocks for determining registration, study etc.

The addition is intended for libraries that import patron data (name, address etc.) from other external system(s) using p_file_20 or API. For determining term of the registration, the registration-expiry-date is not used. Instead of, the library uses patron global block, some for not-registered users, others for those, who finished their employee, study etc. No registration fees are charged or at least processed in this script. This is mostly case of academic libraries.

## Description
The Library holds all patron data in ALEPH database, but requires user’s consent to use some of its services. The user can log in into ALEPH. After logging in, he/she can get an alert that he/she is not registration (has global blocks) using patron-notice OPAC template. This template contains link to borrower account in OPAC (https://opac.aleph.lib/F/?func=bor-info?registration=Y), OPAC template boar-info-single-adm.  This template is fairly modified: If it is called with URL parameter „registration“, all default content is hidden by JavaScript and a registration form is shown instead. This contains library rules that must be agreed, input for password and button Commit. The password is used for authorising the user, if someone would get erroneous to this page without authorisation. After committing the backend script registration.cgi is called asynchronously (XHR,AJAX). It returns a text response that contains several determined responses (OK, error, etc., see below or in the cgi script), so you can modify the real text of the response to user by your needs or language settings. This response is displayed on the same web page. Moreover, if user access the OPAC borrower account without registration and without “registration” URL argument, he/she is also switched to registration form.

When passing the request, the registration.cgi checks:
a)	global blocks for not-registered (can be more and set at the beginning of the script)
b)	global blocks for finished employee, study, etc. (the same)
c)	patron’s plif-modification settings (in Czech „Chráněná pole“) – when whole record is protected (has value „1“), online registration cannot be passed as ALEPH blocks any updates.
d)	patron card – can be used to alert him/her that he/she must arrange a user card to use library services

Responses of the registration.cgi script to bor-info-single-adm (bor account page):
   `'OK' - successfully newly registered`

   `'OK noCard' - successfully newly registered, but user has no valid Card`

   `'authenticationFailure' - authentication using patron IDs from API and password given by the user (www form) failed.`

   `'alreadyRegistrated '+DD/MM/YYYY  - the patron has been already registered and expiry date`

   `'finishedStudyorJob' - the patron has global block that claims he has finished his study or employment/job, registration cannot be passed`

   `'error '+text of the error message.`

   `'plifModificationAll' - the whole patron record is protected by z303-plif-modification settings. It cannot be updated by api or procedure.`

After successful registration:
-	user gets response (see above);
-	global blocks for non-registered are removed from his/her account;
-	new event is written to circulation log (z309) including proper circulation event. number/text (can be set in the cgi script) and IP address;
-	patron registration date (z305-registration-date) is update to current date.
-	text log in CGI directory is written ($httpd_root/cgi-bin/ online_registration.log).

## Implementation
Save registration.cgi into your Apache CGI directory and make the file executable. Edit this file and check the initial variable (constants) according to your local environment:
`#initial variables`

`my $adm_base="xxx50"; #lower case`

`my $xserver_url="https://catalogue.library.gen/X";`

`my $xborinfo_user="X-BOR-INFO"; #aleph user with privilegies to both bor-info and bor-auth x-services and Patron Record - Display`

`my $xborinfo_user_pas="xxxxxxxxx"; #password to this`

`my $xborupd_user="X-BOR-INFO"; #aleph user with privilegies to bor-update x-service and Patron Record - Update`

`my $xborupd_user_pas="xxxxxxxxx"; #password to this`

`my @block_not_registrated=(50); #array with values of global block for not registered patrons`

`my @block_finished=(51,52); #array with values of global block for patrons with finished study or employment. These cannot be registered.`

`my $libraryCardIDtype='01'; #type of Aleph ID used for library (student, staff) cards, for checking if user has a valid card`

`my $defaultAlephCardPrefix='BC-'; #For user without card. As Aleph sets own value for mandatory field ID, identify it here by value set in util h 2, last-bor-id-1 `

`my $log='online_registration.log'; #for writing registrations, alerts and errors`

`my $sid = 'dbi:Oracle:host=localhost;sid=aleph23'; #Oracle System Identifier - SID. It is needed for updating the circulation log / z309 table`

`my $circ_log_event_no=92; #event no. to be written in circulation log (z309, Z309_ACTION)`

`my $circ_log_event_text="Online registration"; #event text to be written in circ. log (z309)`

`my $admin_mail='best.librarian@library.gen'; #for sending errors etc.`

`my $debug='1'; #debug mode, sends all registrations to admin_email, not just errors`



Modify the OPAC template **bor-info-single-adm** according to an example in Code section. The original content of the page should be bounded into element `<div id="borAccount">`. The newly added registration is to be bounded in another div, by default hidden: `<div id="registration" style="display: none;">`
Behind the both html section, add JavaScripts for manipulation: hiding display these elements and managing the html form – send data asynchronously and processing the returned cgi response. Here you may modify the text responses displayed to user according to local and language environment, change styles or modify ./icon/f-cekej.gif (waiting animation)
In the standard bor-account, the elements that show patron blocks (placeholders $2100-$3200) should be marked with class „blocks“. This is used for alerting non-registration when accessing the borrower account. The line „if ( blockTexts.indexOf….“ in the manipulation JavaScript must be changed – in the if condition modify the text according to your local naming of the block for non-registered.

In standard view add

`<!--registration--><p id="onlineRegistrationNotice" style="display: none;">Zaregistrujte se <a href="javascript:void(0)" onclick="switch2registration();">online</a> nebo v knihovně.</a><br></p>`


OPAC template **patron-notice** (alert after logging in].  If you use global blocks for not-registered and finished study/job only, and the finished users cannot log in, you can simply add/modify the text for showing block to info about registration, as it is in the example in Codes. (this html block is shown/hidden using style.display and Aleph placeholder $2000). Otherwise, you probably must modify the view according to displayed texts of blocks.

**.../ADMlib/tab/tab/tab_circ_log.{lng}** - add new event number and description for online reg. according to new event set in registration.cgi script.


## Workflow of the **registration.cgi** script
1.	get all patron logins from x-server api (op=bor-info, response used also in checks below)
2.	authenticate user using all these logins and password typed by user – x-server (op=bor-auth)
3.	Check if user has card (ID with type used as library card) 
4.	Check global blocks – finished study or job
5.	Check global blocks – block “not registrated”
6.	Check plif-modification settings (“Chráněná pole“ in Czech)
If all OK the process registration:
7.	Modify patron record (plif xml): delete block of “non-registered”, and add registration date
8.	upload updated borrower record (x-server, update-bor)
9.	write circulation log = z309 (sql)
10.	write text log
11.	text reponse to user (web)



## Languages, Dependences
Aleph version 22/23 with X-Server, CGI (Apache), Perl 5.8 with modules LWP, URI:Escape, XML::Simple, CGI, DBI, Data::Dumper; Javascript ECMAScript 2016




## License, author
GNU GPL3, by Matyas F. Bajger, University of Ostrava, University Library, https://library.osu.eu, in May 2021

